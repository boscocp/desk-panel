package dev.bosco.deskpanel;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import androidx.core.app.ServiceCompat;

/**
 * Owns the poll loop, so that the loop outlives the screen (ADR 0014).
 *
 * <p>This component exists because of a contradiction T4.3 walks into.
 * Invariant 3 says the panel must clear {@code FLAG_KEEP_SCREEN_ON} when the PC
 * goes away and let Android sleep the display — and the display going out
 * delivers {@code onPause} and {@code onStop} to the foreground Activity. While
 * {@link PcPoller} was started in {@code onResume} and stopped in {@code
 * onPause}, the moment the panel did what it exists to do it switched off the
 * only thing that would have noticed the PC coming back. The wake marker
 * could never fire.
 *
 * <p>So the loop moved out of the Activity's lifecycle and into a foreground
 * service, which keeps running while the Activity is stopped. Three things it
 * buys, and each one is a separate reason:
 *
 * <ol>
 *   <li><b>MIUI.</b> The project's oldest trap is that MIUI's battery manager
 *       freezes background apps. A bare background thread in a stopped Activity
 *       is precisely what it freezes; a foreground service is the documented
 *       way to say "this is the thing the user is looking at". It does not
 *       replace the manual autostart and battery-exemption toggles in
 *       {@code docs/INSTALL-PHONE.md} — it is what makes them effective.
 *   <li><b>The CPU.</b> A foreground service does not keep the CPU awake. With
 *       the screen off, the device suspends and a {@code ScheduledExecutor}
 *       simply stops firing, so a login would go unnoticed until something else
 *       woke the phone. Hence {@link #offlineWakeLock}, held for exactly the
 *       stretch where nothing else is keeping the device up.
 *   <li><b>The wake.</b> {@code setTurnScreenOn} only fires when the Activity is
 *       resumed, and nothing resumes a stopped Activity on its own. The service
 *       brings it to the front, which is a background activity start — allowed
 *       here because the app has an activity in the back stack of a task on the
 *       Recents screen, one of the documented exemptions.
 * </ol>
 *
 * <p>It holds no product logic. {@link PcState} decides what a probe means,
 * {@link PcPoller} owns the socket and the schedule, {@code MainActivity} owns
 * the window. This is the thing that stays awake.
 */
public final class PanelService extends Service implements PcPoller.Listener {

    /**
     * The panel's window, as much of it as this service is allowed to know.
     * {@code MainActivity} implements it and registers itself; the service
     * never holds a reference to anything else of the Activity's.
     */
    public interface Panel {
        /** Called on the main thread, on transitions only. */
        void onPcState(boolean online);
    }

    private static final String CHANNEL_ID = "panel";
    private static final int NOTIFICATION_ID = 1;

    /**
     * The registered panel, or null when no Activity is alive. Static because
     * the Activity and the service are separate components with no lifecycle
     * relationship to hang a binding off: the service is started, not bound, so
     * that it survives an Activity that has been stopped for hours.
     *
     * <p>A static field holding an Activity is a leak if it is ever left
     * behind, so {@code MainActivity} clears it in {@code onDestroy} and this
     * class never caches it in a local field.
     */
    private static volatile Panel panel;

    private PcPoller poller;

    /**
     * Held while the PC is offline, and only then. Online, {@code
     * FLAG_KEEP_SCREEN_ON} already keeps the device up and this would be a
     * second, redundant claim on it.
     *
     * <p>Why a wake lock is affordable here at all: the phone is powered from
     * the PC's USB, and on this rig the board keeps that USB live even with the
     * PC shut down, so "offline" does not mean "on battery" — it means charging
     * with the screen off. The cost is a little heat, not an overnight
     * discharge. That assumption is recorded in ADR 0014, together with what has
     * to change if ErP Ready is ever disabled as {@code docs/DEVICE-CARE.md}
     * recommends, which would make the USB die with the PC.
     */
    private PowerManager.WakeLock offlineWakeLock;

    /** Registers the Activity that owns the window. */
    public static void setPanel(Panel newPanel) {
        panel = newPanel;
    }

    /**
     * Unregisters {@code oldPanel}, but only if it is still the one registered.
     *
     * <p>Not a plain null assignment, because the two orders an Activity can be
     * replaced in are both real. A relaunch — which a wake from a doze can
     * cause, by way of a configuration change — may run the new instance's
     * {@code onCreate} before the old instance's {@code onDestroy}. A blind
     * clear there would unregister the live panel on behalf of a dead one, and
     * the failure is silent and total: the markers keep coming, because the
     * service logs them, while the page is never told anything again and sits
     * on whatever it last rendered.
     */
    public static void clearPanel(Panel oldPanel) {
        if (panel == oldPanel) {
            panel = null;
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();

        PowerManager power = getSystemService(PowerManager.class);
        offlineWakeLock = power.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "DeskPanel:offline-poll");
        // Released by hand, on the transition back to online. Reference
        // counting would make a second acquire need a second release, and this
        // lock is a state, not a stack.
        offlineWakeLock.setReferenceCounted(false);

        // R.string.pc_host carries the address the build baked in from .env.
        poller = new PcPoller(getString(R.string.pc_host), this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        // Before anything else: an app that called startForegroundService has a
        // few seconds to get here or the system kills it with an ANR.
        ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                buildNotification(),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);

        // start() is idempotent, so a redelivered or repeated command cannot
        // leave two loops running.
        poller.start();

        // START_STICKY: if MIUI kills the process anyway, the panel should come
        // back watching rather than stay dark with the PC on. The intent is
        // null on that restart and nothing here reads it.
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        poller.stop();
        if (offlineWakeLock.isHeld()) {
            offlineWakeLock.release();
        }
        super.onDestroy();
    }

    /** Started, never bound — see the note on {@link #panel}. */
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    /**
     * One PC transition, on the main thread, from {@link PcPoller}.
     *
     * <p>Order matters, and it is: marker, then wake lock, then the window,
     * then the front. The wake lock is taken <em>before</em> the screen is
     * allowed to go out, so there is no window in which the device may suspend
     * with nothing holding it; and released <em>after</em> the Activity has
     * been asked forward, so the wake itself cannot be cut short by the CPU
     * going down between the two calls.
     */
    @Override
    public void onPcState(boolean online) {
        Log.i(Markers.TAG, Markers.state(online));

        if (!online && !offlineWakeLock.isHeld()) {
            offlineWakeLock.acquire();
        }

        Panel target = panel;
        if (target != null) {
            target.onPcState(online);
        }

        if (online) {
            bringPanelToFront();
            if (offlineWakeLock.isHeld()) {
                offlineWakeLock.release();
            }
        }
    }

    /**
     * Resumes the Activity, which is what actually turns the screen on:
     * {@code setTurnScreenOn(true)} is a property of the Activity's window and
     * fires when that window next becomes visible, not when it is set.
     *
     * <p>{@code REORDER_TO_FRONT} rather than a plain launch, so the existing
     * task is raised instead of a second one being created.
     *
     * <p>It does not keep the Activity <em>instance</em>: measured on the
     * device, MIUI relaunches it on the way back from a doze, the page reloads,
     * and a {@code panel=rendered} lands about a second after the wake
     * marker. That is left as it is — a reload costs a second of an
     * already dark screen — but anything counting that marker across a wake has
     * to allow for it (ADR 0014).
     */
    private void bringPanelToFront() {
        Intent panelIntent = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                        | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        startActivity(panelIntent);
    }

    /**
     * The channel is the lowest importance that still shows: this notification
     * is the price of the service, not something to read. It is invisible in
     * normal use anyway — the panel hides the status bar (T2.3), and the rest
     * of the time the screen is off.
     */
    private void createNotificationChannel() {
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Desk Panel", NotificationManager.IMPORTANCE_MIN);
        channel.setDescription("Keeps watching the PC while the screen is off.");
        channel.setShowBadge(false);
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    private Notification buildNotification() {
        PendingIntent open = PendingIntent.getActivity(
                this,
                0,
                new Intent(this, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
                PendingIntent.FLAG_IMMUTABLE);

        return new Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("Desk Panel")
                .setContentText("Watching the PC")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentIntent(open)
                .setOngoing(true)
                .build();
    }

    /** Starts the service, from wherever the panel is being brought up. */
    public static void start(Context context) {
        context.startForegroundService(new Intent(context, PanelService.class));
    }

    /** Stops it, when the panel is genuinely going away rather than pausing. */
    public static void stop(Context context) {
        context.stopService(new Intent(context, PanelService.class));
    }
}
