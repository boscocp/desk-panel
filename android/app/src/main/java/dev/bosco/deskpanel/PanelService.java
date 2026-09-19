package dev.bosco.deskpanel;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.ServiceInfo;
import android.os.BatteryManager;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import androidx.core.app.ServiceCompat;
import androidx.core.content.ContextCompat;

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
        /**
         * Called on the main thread.
         *
         * @param online        the PC state to apply to the window and the page
         * @param logTransition whether this is a state <em>change</em> the panel
         *                      should log, as opposed to a replay handed to a
         *                      window that was not around when the change
         *                      happened. A replay must not log: the marker
         *                      contract is one line per transition, and an
         *                      Activity relaunch is not a transition.
         */
        void onPcState(boolean online, boolean logTransition);

        /**
         * A fresh data payload for the page (T5.1).
         *
         * @param json a JSON object literal, already safe to interpolate
         */
        void onData(String json);
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

    /**
     * The last state the poller reported, or null before the first probe.
     *
     * <p>{@link PcPoller} delivers edges and nothing else, which is what keeps
     * the log honest — and it means a window that appears <em>between</em> two
     * transitions would otherwise never be told anything at all. Two ways that
     * happens, both real on this device: MIUI relaunches the Activity on the way
     * back from a doze, and {@code START_STICKY} can restart the service into a
     * process with no Activity in it. Without a replay the newcomer would sit in
     * whatever state {@code onCreate} guessed — holding {@code
     * FLAG_KEEP_SCREEN_ON} through an offline night, which is the invariant this
     * whole wave exists to enforce.
     */
    private static volatile Boolean lastOnline;

    /**
     * Set when a transition was reported with no panel registered, so the replay
     * that follows logs the screen marker instead of swallowing it.
     *
     * <p>This is the {@code START_STICKY} path. The service comes back without
     * an Activity, the first probe is a genuine transition, and the window that
     * finally registers is the one that acts on it — so that window's marker is
     * the transition's, just late.
     */
    private static volatile boolean screenMarkerPending;

    /**
     * The last payload the page was given, replayed to a window that arrives
     * late for the same reason {@link #lastOnline} is. The data refreshes once
     * a minute, so without this a wake would show an empty panel for up to a
     * minute after the screen came back — which is exactly the moment somebody
     * is looking at it.
     *
     * <p>This is the <em>folded</em> payload: server data plus
     * {@link #lastBattery}. What the page last saw, in other words, which is
     * also what {@link #publish} compares against to decide whether a battery
     * broadcast is worth a render.
     */
    private static volatile String lastPayload;

    /**
     * The server half, before the battery is folded in. Kept apart from
     * {@link #lastPayload} because the two halves arrive on different clocks
     * and either one has to be able to refresh the page with the other's last
     * value still on it.
     */
    private static volatile String lastServerPayload;

    /**
     * The device half: the most recent battery broadcast, as the object literal
     * {@link BatteryReading} builds. Not cleared when the PC goes away — unlike
     * the server data, a battery level does not go stale by being offline, it
     * is simply the last thing the phone said about itself.
     */
    private static volatile String lastBattery;

    /**
     * The running service, for the static entry points that have to reach an
     * instance field. Null between destroy and create.
     */
    private static volatile PanelService instance;

    private PcPoller poller;

    /**
     * Runs only while the PC is online. Offline the panel is dark and the
     * device is up on a wake lock held to notice a login; spending that on
     * numbers nobody can see is the opposite of what ADR 0008 asks for.
     */
    private DataPoller dataPoller;

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

    /**
     * Registers the Activity that owns the window, and immediately replays the
     * current PC state to it if one is known. See {@link #lastOnline} for why a
     * replay is not optional.
     */
    public static void setPanel(Panel newPanel) {
        panel = newPanel;
        Boolean state = lastOnline;
        if (newPanel != null && state != null) {
            boolean logIt = screenMarkerPending;
            screenMarkerPending = false;
            newPanel.onPcState(state, logIt);
        }
        String payload = lastPayload;
        if (newPanel != null && payload != null) {
            newPanel.onData(payload);
        }
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
        instance = this;
        createNotificationChannel();

        PowerManager power = getSystemService(PowerManager.class);
        offlineWakeLock = power.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "DeskPanel:offline-poll");
        // Released by hand, on the transition back to online. Reference
        // counting would make a second acquire need a second release, and this
        // lock is a state, not a stack.
        offlineWakeLock.setReferenceCounted(false);

        // R.string.pc_host carries the address the build baked in from .env.
        String host = getString(R.string.pc_host);
        poller = new PcPoller(host, this);
        dataPoller = new DataPoller(host, this::onData);

        // RECEIVER_NOT_EXPORTED because nothing outside the system should be
        // able to tell this app what the battery is doing.
        // ACTION_BATTERY_CHANGED is sticky, so this call itself delivers the
        // current reading straight away rather than waiting for the phone to
        // change its mind — which is what makes the panel show a level within a
        // second of starting instead of within an hour.
        ContextCompat.registerReceiver(
                this,
                batteryReceiver,
                new IntentFilter(Intent.ACTION_BATTERY_CHANGED),
                ContextCompat.RECEIVER_NOT_EXPORTED);
    }

    /**
     * One merged payload, on the main thread, from {@link DataPoller}.
     *
     * <p>Held as well as forwarded, so a window that appears between two
     * refreshes is not left blank — the same replay {@link #lastOnline} gets.
     */
    private void onData(String json) {
        lastServerPayload = json;
        publish();
    }

    /**
     * Folds the two halves together and hands the result to the page, if it
     * differs from what the page already has.
     *
     * <p>The comparison is not an optimisation, it is what makes a push-based
     * battery affordable. {@code window.onData} is a full re-render — {@code
     * app.js} rebuilds every card from scratch — and {@code
     * ACTION_BATTERY_CHANGED} fires on voltage and temperature movements that
     * change nothing anybody can see at one decimal place. Without this, a
     * charging phone would repaint the whole panel every few seconds to draw
     * the same characters, on a display whose whole power story is that
     * unchanged pixels cost nothing (ADR 0008).
     */
    private void publish() {
        String folded = DataPayload.withBattery(lastServerPayload, lastBattery);
        if (folded == null || folded.equals(lastPayload)) {
            return;
        }
        lastPayload = folded;
        Panel target = panel;
        if (target != null) {
            target.onData(folded);
        }
    }

    /**
     * One {@code ACTION_BATTERY_CHANGED}, which Android sends rather than
     * letting anybody ask (T5.4 step 5: polling this would spend exactly the
     * power the reading exists to protect).
     *
     * <p>Registered by the service rather than the Activity, and that is the
     * one design decision here. The receiver has to be alive whenever there is
     * a payload to fold it into, and the Activity is stopped for the entire
     * offline stretch — so an Activity-scoped receiver would be gone precisely
     * when the phone is running warm on a wake lock in a dark room, which is
     * the case this number is for.
     */
    private final BroadcastReceiver batteryReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            int level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, BatteryReading.ABSENT);
            int scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, BatteryReading.ABSENT);
            int tenths = intent.getIntExtra(
                    BatteryManager.EXTRA_TEMPERATURE, BatteryReading.ABSENT);
            // EXTRA_PLUGGED, not EXTRA_STATUS. The panel's claim is "the cable
            // is in", and STATUS does not answer that question: a phone reports
            // BATTERY_STATUS_NOT_CHARGING whenever charging is paused with
            // power still connected, which on this device is the normal state
            // every time MIUI's charge optimisation or a thermal limit steps in,
            // and on many devices is what sitting at 100% on a charger looks
            // like. Reading STATUS would put "unplugged" on the panel with the
            // cable plainly in -- and that word is not decoration: STATUS.md
            // uses this line as the evidence for whether ADR 0014's wake lock
            // is still affordable, so a false "unplugged" argues for rewriting
            // the poll loop to solve a problem that does not exist.
            boolean plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0;
            String reading = BatteryReading.json(level, scale, tenths, plugged);
            if (reading == null) {
                return;
            }
            // Per broadcast, not per change: this marker is the only evidence
            // that the receiver is firing at all, and a receiver that silently
            // never fires is the failure T5.4 names. The render below is the
            // half that is rate-limited.
            Log.i(Markers.TAG, Markers.battery(BatteryReading.percent(level, scale)));
            lastBattery = reading;
            publish();
        }
    };


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
        dataPoller.stop();
        unregisterReceiver(batteryReceiver);
        releaseOfflineWakeLock();
        instance = null;
        super.onDestroy();
    }

    private void releaseOfflineWakeLock() {
        if (offlineWakeLock.isHeld()) {
            offlineWakeLock.release();
        }
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
     * with nothing holding it. It is <em>not</em> dropped here on the way back
     * up — that waits for proof the window is actually visible, in
     * {@link #panelVisible()}.
     */
    @Override
    public void onPcState(boolean online) {
        Log.i(Markers.TAG, Markers.state(online));
        lastOnline = online;

        if (!online && !offlineWakeLock.isHeld()) {
            offlineWakeLock.acquire();
        }

        Panel target = panel;
        if (target != null) {
            target.onPcState(online, true);
        } else {
            // No window to act on it. Whoever registers next owns this
            // transition, marker included.
            screenMarkerPending = true;
        }

        if (online) {
            // Started only now, and stopped below: the data poll exists to
            // keep a visible panel current, and there is no visible panel
            // while the PC is away (T5.1 step 4).
            dataPoller.start();
            bringPanelToFront();
        } else {
            dataPoller.stop();
            // Dropped, not kept. It is only ever written by a successful
            // fetch, so holding it would mean the wake after a night offline
            // replays last night's prices and weather -- with stale:false,
            // because nothing in the payload knows how old it is. The panel
            // is blank for the second or two until DataPoller's first fetch
            // lands, and blank is honest where a confident wrong number is
            // not.
            //
            // Both halves, because withBattery() would otherwise rebuild the
            // folded payload out of the server data this line exists to
            // forget. lastBattery survives on purpose: it is the phone's own
            // reading, and it is exactly as true offline as online.
            lastServerPayload = null;
            lastPayload = null;
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
        // NEW_TASK as well as REORDER_TO_FRONT: a PendingIntent starts its
        // activity from outside any activity context, and with no task left to
        // reorder — the app was killed, or the card was swiped away while the
        // service kept running — REORDER_TO_FRONT alone has nothing to act on.
        // This notification is the one way a human can reach a panel whose
        // screen is dark, so it has to work in exactly that case.
        PendingIntent open = PendingIntent.getActivity(
                this,
                0,
                new Intent(this, MainActivity.class)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                                | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT),
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

    /**
     * Stops the service when the panel is genuinely going away — but only if no
     * other window has claimed it in the meantime.
     *
     * <p>The same argument as {@link #clearPanel}, and it needs the same care. A
     * departing Activity's {@code onDestroy} can run after its replacement's
     * {@code onCreate} has already called {@link #start}; an unguarded {@code
     * stopService} there would tear down the service the live window just
     * started, and nothing would restart it. The panel would then never notice
     * the PC again — no marker, no crash, just a page that stopped changing.
     */
    public static void stopIfUnclaimed(Context context) {
        if (panel == null) {
            context.stopService(new Intent(context, PanelService.class));
        }
    }

    /**
     * Called when the panel's window actually has focus, which is the first
     * moment anything can be sure the display is on.
     *
     * <p>This is where the offline wake lock is dropped, rather than at the
     * {@code startActivity} that asked for the wake. {@code startActivity} only
     * hands the request to the ActivityManager and returns — the resume, and
     * with it {@code setTurnScreenOn}, happen afterwards — so releasing there
     * would drop the app's only claim on the CPU while the wake was still in
     * flight. It also matters in the failure MIUI actually produces: if "Show on
     * Lock screen" is denied the window never comes up, and holding the lock is
     * what keeps the poll loop alive to try again rather than letting the device
     * suspend with the PC plainly on.
     */
    public static void panelVisible() {
        PanelService service = instance;
        if (service != null && Boolean.TRUE.equals(lastOnline)) {
            service.releaseOfflineWakeLock();
        }
    }
}
