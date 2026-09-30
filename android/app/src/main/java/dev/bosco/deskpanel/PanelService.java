package dev.bosco.deskpanel;

import android.app.AlarmManager;
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
import android.os.SystemClock;
import android.util.Log;

import androidx.core.app.ServiceCompat;
import androidx.core.content.ContextCompat;

import java.util.Calendar;

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
 *       woke the phone. Hence {@link #offlineWakeLock} — held for the offline
 *       stretch <em>while the phone is on mains</em>, and deliberately not
 *       while it is on its own battery, where the device is supposed to
 *       suspend and {@code AlarmManager} keeps the time instead (T5.6, the
 *       follow-up branch ADR 0014 specifies).
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
         * One thermal verdict (T5.5, ADR 0012).
         *
         * <p>No {@code logTransition} twin of {@link #onPcState}'s, and the
         * asymmetry is the point. A PC transition <em>is</em> the screen event,
         * so the service knows when it is worth a marker. A thermal verdict is
         * not: the device can cross 45 degrees while the panel is already dark
         * because the PC is away, where nothing blanks and there is nothing to
         * report. The window is the only thing that knows whether a verdict
         * actually took the panel out, so the window logs it — see
         * {@code MainActivity.applyBrightness}.
         *
         * <p>Two authorities arrive as two calls rather than as one combined
         * verdict because each is applied by a different mechanism, and only
         * the window can apply either. What must not be duplicated is the
         * <em>decision</em>, and that lives in one place,
         * {@code MainActivity.applyScreenState}.
         *
         * @param tooHot whether the device is too hot to keep painting
         */
        void onThermal(boolean tooHot);

        /**
         * Whether the night profile is in force (T6.4).
         *
         * <p>Delivered the same way {@link #onThermal} is, and for the same
         * reason: only the window can reach {@code screenBrightness}, and the
         * decision must not be made twice. What the window does with it is a
         * third brightness, not a third blackout — the panel at night is lit,
         * dimly, because a dark room is exactly when somebody glances at a
         * clock.
         *
         * <p>Nothing about the page rides this call. {@code js/app.js} asks
         * {@code isNight} in {@code web/js/format.js} the same question about
         * the same payload, so the glow drops without a round trip through
         * Java — and so the profile can be developed in a browser, where
         * there is no Java at all. See {@link NightWindow} for why that is a
         * deliberate second implementation rather than a missed chance to
         * share one.
         *
         * @param night whether the device's own clock is inside the window
         *              the PC's config describes
         */
        void onNight(boolean night);

        /**
         * A fresh data payload for the page (T5.1).
         *
         * @param json a JSON object literal, already safe to interpolate
         */
        void onData(String json);

        /**
         * One spectrum frame for the page (T8.5), twenty a second while the
         * PC streams them. Not replayed to a window that registers late: a
         * frame is stale a twentieth of a second after it arrives.
         *
         * @param frame 32 lowercase hex digits, checked by {@link SpectrumFrame}
         */
        void onSpectrum(String frame);
    }

    private static final String CHANNEL_ID = "panel";
    private static final int NOTIFICATION_ID = 1;

    /**
     * The sparse offline probe's alarm, as a package-scoped broadcast (T5.6).
     * Scoped rather than implicit: nothing outside this app has any business
     * waking its poll loop.
     *
     * <p>It is the <em>only</em> mechanism whenever the phone's power does not
     * change with the PC — a wall charger, or a board that keeps USB live with
     * the PC off. {@code ACTION_POWER_CONNECTED} is the fast path, not the
     * guarantee, so fifteen minutes is the worst case that actually has to be
     * acceptable rather than a number the fast path excuses.
     */
    private static final String ACTION_DORMANT_PROBE = "dev.bosco.deskpanel.DORMANT_PROBE";

    /**
     * How long to hold the CPU for one dormant probe, as a timeout rather than
     * a matching release.
     *
     * <p>The alarm's own implicit wake lock covers {@code onReceive} and
     * nothing after it, and the probe is blocking I/O handed to another thread
     * — so without a lock of our own the device can suspend mid-probe and the
     * result arrives whenever something else happens to wake the phone. A
     * timeout rather than a release in a callback because the failure modes are
     * not symmetric: a lock released a few seconds late costs a few seconds of
     * CPU, and a lock whose release never runs costs the battery this task
     * exists to save. The platform drops it either way.
     *
     * <p>10s against a probe whose worst case is the connect and read timeouts
     * back to back, 3s (see {@code PcPoller.TIMEOUT_MS}), per host -- and an
     * offline cycle asks every host, so {@link PcHosts#MAX_HOSTS} is 3 to keep
     * the whole cycle, 9s, inside this window (ADR 0016).
     */
    private static final long PROBE_WINDOW_MS = 10_000L;

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
     * The thermal authority (T5.5), fed from the battery broadcast below.
     *
     * <p>Static, and therefore outliving a {@code START_STICKY} restart of this
     * service, because the device does not cool down just because a process
     * came back. A fresh instance would start at "not too hot" and paint into a
     * phone that is still at 46 degrees, which is the state this class exists
     * to leave.
     */
    private static final ThermalState thermal = new ThermalState();

    /**
     * Whether heat is currently what is keeping the panel dark — the state the
     * thermal marker reports, and the reason that marker is emitted here rather
     * than by the window.
     *
     * <p>It is the conjunction {@code online && tooHot}, and no single component
     * knows both halves except this one. The window knows whether it is blanked,
     * but a window blanked while the PC is away has taken nothing off the
     * screen: the display is already out under the PC's mechanism, so a marker
     * there would claim an event nobody could see. This field also survives an
     * Activity recreation, which a field on the window does not — and MIUI
     * relaunches the Activity on every wake from doze, so a per-window flag
     * emits a second {@code screen=thermal} for one thermal event.
     */
    private static volatile boolean thermalDark;

    /**
     * The last thermal verdict, or null before the first usable temperature.
     * Replayed to a window that registers late for exactly the reason
     * {@link #lastOnline} is: the verdict is delivered as an edge, and a window
     * that arrives between two edges would otherwise never hear it at all.
     */
    private static volatile Boolean lastTooHot;

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
     * The night profile's window, as the last payload described it, or null
     * while no payload has carried a usable one (T6.4).
     *
     * <p><b>Not cleared when the PC goes away</b>, unlike
     * {@link #lastServerPayload} beside it, and the difference is what the two
     * hold. A price is a measurement and goes stale; this is configuration —
     * two strings a human edits in {@code server/config.toml} — and it is
     * exactly as true at midnight with the PC off as it was at ten. Keeping it
     * is what makes a 23:00 login come up dim immediately instead of at full
     * brightness for the minute until the first payload lands, which is the
     * one minute the profile exists for.
     */
    private static volatile NightWindow nightWindow;

    /**
     * Whether the night profile is currently in force — the state the
     * {@code night=} marker reports, and the reason it is emitted here rather
     * than by the window.
     *
     * <p>It is the conjunction {@code online && inside the window}: offline
     * the screen is asleep and a dimmer backlight behind a display that is
     * out is not a thing anybody can see, so there is nothing to claim. Heat
     * is deliberately <em>not</em> part of it. A hot night is two independent
     * facts and the log says both — {@code night=on} beside
     * {@code screen=thermal} — where a conjunction would have swallowed one
     * of them and left the morning's {@code screen=thermal-clear} arriving
     * next to a profile nobody could tell the state of.
     *
     * <p>Static for the reason {@link #thermalDark} is: MIUI recreates the
     * Activity on every wake from doze, and a per-window flag would emit a
     * second {@code night=on} for one nightfall.
     */
    private static volatile boolean nightDim;

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
     * Whether the charger is connected, from {@code EXTRA_PLUGGED} (T5.4).
     * True until the first broadcast says otherwise, which is the same safe
     * default {@code PcPoller} starts from: no broadcast means behave as the
     * app did before T5.6 rather than go dormant on a charging phone.
     */
    private static volatile boolean onMains = true;

    /**
     * Whether the loop is currently dormant, so the marker fires on the
     * transition and not on every fifteen-minute cycle. {@code onDormant} is
     * called after every dormant probe by design — it is what re-arms the alarm
     * — so this is what keeps {@code dormant=} one line per change, the same
     * contract {@code state=} and {@code screen=} keep.
     */
    private static volatile boolean dormant;

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

    /** The spectrum bars' stream (T8.5), on the data poller's schedule. */
    private SpectrumStream spectrumStream;

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
     * Held for one dormant probe and released by its own timeout (T5.6).
     *
     * <p>A second lock rather than a timed acquire on {@link #offlineWakeLock},
     * and the reason is that the two have different disciplines: this one is
     * always timed and always short, that one is untimed and released by a
     * window gaining focus. Mixing them means calling {@code acquire(timeout)}
     * and {@code acquire()} on one object, and whether the second cancels the
     * first's pending release is a detail of the platform's implementation
     * rather than of its documentation — the kind of thing ADR 0009's reasoning
     * says not to build on. Two objects have no such question.
     */
    private PowerManager.WakeLock probeWakeLock;

    /** Keeps the sparse offline probe's time while this process is asleep (T5.6). */
    private AlarmManager alarms;

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
        Boolean hot = lastTooHot;
        if (newPanel != null && hot != null) {
            newPanel.onThermal(hot);
        }
        // Unconditional, where the two above are guarded, because "no night
        // window yet" and "not night" ask the same thing of the window --
        // full brightness -- whereas "no PC verdict yet" and "offline" ask
        // opposite ones. The same asymmetry MainActivity.tooHot has against
        // MainActivity.lastOnline, one layer up.
        if (newPanel != null) {
            newPanel.onNight(nightDim);
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

        alarms = getSystemService(AlarmManager.class);

        // Reset, because the poller this service is about to build starts from
        // UNKNOWN and is therefore not dormant. The flag is static so that it
        // survives an Activity, not a service: left stale-true across a
        // recreate it would swallow the next `dormant=on` — the one line
        // TESTING.md scenario 6 and T5.6's acceptance both grep for.
        dormant = false;

        PowerManager power = getSystemService(PowerManager.class);
        offlineWakeLock = power.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "DeskPanel:offline-poll");
        // Released by hand, on the transition back to online. Reference
        // counting would make a second acquire need a second release, and this
        // lock is a state, not a stack.
        offlineWakeLock.setReferenceCounted(false);

        probeWakeLock = power.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK, "DeskPanel:probe");
        probeWakeLock.setReferenceCounted(false);

        // R.string.pc_host carries the addresses the build baked in from .env,
        // comma-separated; one PcHosts is shared so the data poller follows
        // whichever PC the PC poller last heard from (ADR 0016).
        PcHosts hosts = PcHosts.parse(getString(R.string.pc_host));
        poller = new PcPoller(hosts, this);
        dataPoller = new DataPoller(hosts, new PanelLink(BuildConfig.PANEL_KEY), this::onData);
        spectrumStream = new SpectrumStream(hosts, new PanelLink(BuildConfig.PANEL_KEY),
                this::onSpectrum);

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

        IntentFilter wakeFilter = new IntentFilter(Intent.ACTION_POWER_CONNECTED);
        wakeFilter.addAction(ACTION_DORMANT_PROBE);
        ContextCompat.registerReceiver(
                this, wakeReceiver, wakeFilter, ContextCompat.RECEIVER_NOT_EXPORTED);
    }

    /**
     * One merged payload, on the main thread, from {@link DataPoller}.
     *
     * <p>Held as well as forwarded, so a window that appears between two
     * refreshes is not left blank — the same replay {@link #lastOnline} gets.
     */
    private void onData(String json) {
        lastServerPayload = json;
        // Re-evaluated here and nowhere on a clock of its own (T6.4 step 4).
        // A timer would be one more thing running on a device whose whole
        // power story is that it does as little as possible, to answer a
        // question that changes twice a day -- and this path already runs
        // once a minute while the panel is lit, which is the resolution the
        // profile is specified at.
        //
        // Before publish(), not after: publish() returns early when the
        // folded payload is unchanged, and the window must be re-read from a
        // payload whose bounds a human may have just edited on the PC even
        // when every price in it is the same.
        nightWindow = NightWindow.parse(json);
        updateNight();
        publish();
    }

    /**
     * One spectrum frame, on the main thread, from {@link SpectrumStream}.
     * Forwarded and never held: see {@link Panel#onSpectrum}.
     */
    private void onSpectrum(String frame) {
        Panel target = panel;
        if (target != null) {
            target.onSpectrum(frame);
        }
    }

    /**
     * Applies the night profile to the window and emits {@code night=} on its
     * edges (T6.4).
     *
     * <p>Called from the two places that can change the answer -- a refresh,
     * which may carry new bounds, and a PC transition, which is what the
     * {@code online} half of the conjunction is -- and from nowhere else.
     *
     * <p><b>What the marker claims is "the panel is running its night
     * profile"</b>, which is the same shape of claim the thermal marker makes
     * and is why both live in this class: {@link #nightDim} survives the
     * Activity recreation that every wake from doze causes, and a flag on the
     * window does not.
     */
    private void updateNight() {
        NightWindow window = nightWindow;
        boolean night = Boolean.TRUE.equals(lastOnline)
                && window != null
                && window.covers(NightWindow.minuteOfDay(Calendar.getInstance()));

        Panel target = panel;
        if (target != null) {
            target.onNight(night);
        }

        // The window is told on every evaluation and the log only on a
        // change. The first is idempotent -- MainActivity compares against
        // the brightness it last asked for -- and the second is a contract:
        // one line per transition, the same as state=, screen= and dormant=.
        if (night == nightDim) {
            return;
        }
        nightDim = night;
        Log.i(Markers.TAG, Markers.night(night));
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
     * One temperature reading, from the battery broadcast (T5.5).
     *
     * <p>Push, never poll: {@code ACTION_BATTERY_CHANGED} arrives about every
     * eight seconds on this device while charging, and asking for the
     * temperature on a schedule of our own would spend exactly the power the
     * reading exists to protect (T5.4 step 5). Invariant 3's "never by a
     * timeout" is untouched — a temperature is a measured condition, not
     * elapsed time.
     *
     * <p><b>Edges only</b>, exactly like {@link #onPcState}. Dispatching every
     * reading was the first cut and it was wrong: this broadcast arrives about
     * every eight seconds on a charging phone, so it would have driven a window
     * update seven times a minute for the life of the panel — including through
     * the offline stretch that T5.6 exists to keep quiet — to re-apply a value
     * that had not changed. A window that registers late is served by
     * {@link #setPanel}'s replay instead, which is what that replay is for.
     */
    private void onThermalReading(double tempC) {
        if (!thermal.record(tempC, SystemClock.elapsedRealtime())) {
            return;
        }
        boolean tooHot = thermal.isTooHot();
        lastTooHot = tooHot;

        Panel target = panel;
        if (target != null) {
            target.onThermal(tooHot);
        }
        updateThermalMarker();
        // No else. A verdict with no window to apply it needs no bookkeeping:
        // lastTooHot above is the whole record, setPanel replays it to whoever
        // registers next, and the marker is this class's own business either
        // way.
    }

    /**
     * Emits {@code screen=thermal} and {@code screen=thermal-clear} on the
     * edges of {@link #thermalDark}.
     *
     * <p><b>What the marker claims is "heat is why the panel you are looking at
     * is dark"</b>, which is the question ADR 0012 says it exists to answer —
     * not "the verdict changed", which would fire overnight with the PC away
     * and the display already out, and not "the window's brightness changed",
     * which would miss the morning login that brings a hot panel up black.
     *
     * <p>Both edges are worth a line, and the falling one has two causes that
     * the log tells apart by what sits next to it: on its own it means the
     * device cooled, and paired with {@code screen=sleep} it means the PC left
     * and now owns the dark. Neither is the panel coming back lit.
     *
     * <p>Called after the window has been told, so the log reads in the order
     * things happened: {@code state=online}, {@code screen=wake},
     * {@code screen=thermal}.
     */
    private void updateThermalMarker() {
        // Boolean.TRUE.equals, not a truthy null: before the first probe there
        // is no PC verdict, and a marker then would be a claim about a state
        // nobody has established. The window is entitled to assume online at
        // startup for the flag it holds; the log is not.
        boolean dark = Boolean.TRUE.equals(lastOnline) && Boolean.TRUE.equals(lastTooHot);
        if (dark == thermalDark) {
            return;
        }
        thermalDark = dark;
        Log.i(Markers.TAG, Markers.thermal(dark));
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

            // The power state, before the reading: this is what decides whether
            // the poll loop may hold the CPU at all (T5.6), and it matters even
            // on a broadcast whose level is unusable and returns below.
            onPowerState(plugged);

            // The temperature, for the same reason and with the same
            // independence: a broadcast whose level extra is missing still
            // carries a usable temperature, and a device at 46 degrees must
            // blank the screen whether or not it can say what percentage it is
            // at. Fed before the return below, never after it.
            if (BatteryReading.plausible(tenths)) {
                onThermalReading(BatteryReading.celsius(tenths));
            }

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


    /**
     * The two things that end dormancy from outside the poll loop (T5.6):
     * power returning, and the alarm coming due.
     *
     * <p>Registered dynamically rather than in the manifest. The process is a
     * foreground service and therefore alive, so a manifest entry buys nothing
     * and would run into the implicit-broadcast restrictions that have applied
     * since API 26.
     */
    private final BroadcastReceiver wakeReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            if (Intent.ACTION_POWER_CONNECTED.equals(intent.getAction())) {
                // Everything this broadcast means is onPowerState's job, the
                // probe included. It used to read `dormant` here and probe
                // afterwards, which was a race between two receivers: plugging
                // in fires ACTION_BATTERY_CHANGED as well, that one also calls
                // onPowerState, and whichever arrived first cleared the flag —
                // so if the battery broadcast won, this one saw "not dormant",
                // skipped the probe, and the alarm had already been cancelled.
                // Nothing would ever have polled again: the panel stays dark
                // with the PC on until the service restarts. The delivery order
                // between two receivers is not ours to depend on, and the
                // device happened to produce the harmless one.
                onPowerState(true);
                return;
            }
            // The alarm. It is armed only while dormant, so there is nothing to
            // decide here: probe, and let the cycle's own reschedule work out
            // whether the schedule goes back to the alarm or stays in-process.
            probeAfterWake();
        }
    };

    /**
     * One power state, from wherever it was learned. Idempotent, so both
     * receivers can call it on every broadcast without comparing edges.
     *
     * <p>It does not probe. Power returning deserves an immediate probe, but
     * the probe belongs to the caller that knows a broadcast just arrived, so
     * that a plain {@code ACTION_BATTERY_CHANGED} in the steady state does not
     * turn into one probe per broadcast.
     */
    private void onPowerState(boolean plugged) {
        // Unconditional and cheap: the poller only reads this at the end of a
        // cycle, so it costs nothing to keep it correct on every broadcast.
        poller.setOnMains(plugged);

        // The rest is edge-only. ACTION_BATTERY_CHANGED arrives about every
        // eight seconds while charging, and cancelling an alarm is a binder
        // call: doing it 450 times an hour to cancel nothing is exactly the
        // kind of small constant cost this task exists to remove.
        if (onMains == plugged) {
            return;
        }
        onMains = plugged;

        // Losing mains changes nothing here. Offline, the wake lock stays up
        // until the next reschedule goes dormant and releases it — at most one
        // BACKOFF_CAP_MS, and the probe that interval ends with needs the CPU
        // anyway. Online, the screen is holding the device regardless.
        if (!plugged) {
            return;
        }

        cancelDormantAlarm();
        boolean wasDormant = dormant;
        setDormant(false);

        // The restored ladder needs something to run on. Out of dormancy the
        // schedule goes back in-process, and while the PC is still away the
        // screen is off — so without this the executor would stop firing the
        // moment the device suspended, with the alarm already cancelled and
        // nothing left to re-arm it. That is ADR 0014's arrangement, and it is
        // affordable for exactly the reason the ADR gives: the phone is on
        // mains again.
        //
        // Keyed on the PC state rather than on dormancy, because the same hole
        // exists where dormancy never happened: mains returning to a phone that
        // has been offline on battery since boot has no `state=` transition for
        // the acquire to hang off.
        if (Boolean.FALSE.equals(lastOnline) && !offlineWakeLock.isHeld()) {
            offlineWakeLock.acquire();
        }

        // And the probe, in the same step that ended dormancy rather than in
        // whichever receiver happens to run next.
        if (wasDormant) {
            probeAfterWake();
        }
    }

    /**
     * One probe, with enough CPU to finish it. The way back from dormancy,
     * shared by the alarm and by power returning.
     *
     * <p>The lock is taken before the probe rather than after, and with a
     * timeout: see {@link #PROBE_WINDOW_MS}. If the probe finds the PC back the
     * ordinary path takes over and {@link #panelVisible()} drops the lock
     * early; if it finds it still gone, {@link #onDormant()} drops it and
     * re-arms.
     */
    private void probeAfterWake() {
        probeWakeLock.acquire(PROBE_WINDOW_MS);
        poller.probeNow();
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
        dataPoller.stop();
        spectrumStream.stop();
        unregisterReceiver(batteryReceiver);
        unregisterReceiver(wakeReceiver);
        // Before the lock, and not optional: an alarm outliving the service it
        // was arming a probe for would wake the phone every fifteen minutes to
        // deliver a broadcast nothing is listening to.
        cancelDormantAlarm();
        releaseOfflineWakeLock();
        releaseProbeWakeLock();
        instance = null;
        super.onDestroy();
    }

    /**
     * Drops the probe's lock once the probe it was taken for has been accounted
     * for, rather than letting {@link #PROBE_WINDOW_MS} run out. That keeps the
     * timeout what it is documented to be — a backstop for a result that never
     * arrives — instead of the normal path: a probe finishing in 100ms was
     * otherwise holding the CPU for ten seconds, ninety-odd times a night, on
     * the one code path whose whole purpose is not to hold it.
     */
    private void releaseProbeWakeLock() {
        if (probeWakeLock.isHeld()) {
            probeWakeLock.release();
        }
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
    public void onPcState(PcState.State state) {
        Log.i(Markers.TAG, Markers.state(state));
        // IDLE -- the PC is up and its display is off -- takes the offline
        // path below whole: the screen sleeps, the data poll stops, the wake
        // lock goes on mains (ADR 0020). Only the marker tells them apart,
        // and PcState keeps the cadence at 2s so the monitor coming back is
        // noticed within one poll.
        boolean online = state == PcState.State.ONLINE;
        // IDLE -> OFFLINE (the PC sleeping after its monitor) is a real edge
        // for the marker, but the screen is already dark: telling the window
        // again would log a second screen=sleep for one dark stretch (found
        // by review).
        boolean stillDark = !online && Boolean.FALSE.equals(lastOnline);
        lastOnline = online;

        // On mains only. Offline on battery the device is *supposed* to
        // suspend, and holding this would be the whole problem T5.6 exists to
        // fix rather than a step towards it — the reschedule that follows this
        // delivery goes dormant instead, and onDormant() takes it from there
        // (ADR 0014's own follow-up branch).
        if (!online && onMains && !offlineWakeLock.isHeld()) {
            offlineWakeLock.acquire();
        }
        if (online) {
            // Nothing sparse is pending any more, and an alarm left armed would
            // wake the phone every fifteen minutes for a probe the 2s ladder is
            // already making.
            cancelDormantAlarm();
            setDormant(false);

            // Taken, not dropped, and this is the one place the word "offline"
            // in the tag is misleading. ADR 0014's rule is that the CPU is held
            // from the decision to wake until the window can be seen to be
            // visible, because startActivity only queues the request -- and
            // panelVisible() is what releases it. Before T5.6 that held by
            // accident: the lock was already up from the offline stretch. Out
            // of dormancy nothing holds it, so the wake would have raced a
            // suspending device, and the probe's own lock is timed and would
            // expire mid-wake.
            if (!offlineWakeLock.isHeld()) {
                offlineWakeLock.acquire();
            }
            // The other end of a dormant probe: this one found the PC, so the
            // lock above has taken over and the probe's own has nothing left to
            // cover. Released rather than left to time out, for the same reason
            // onDormant() releases it — the timeout is the backstop, not the
            // normal path.
            releaseProbeWakeLock();
        }

        Panel target = panel;
        if (stillDark) {
            // Nothing for the window to do; the rest below is idempotent.
        } else if (target != null) {
            target.onPcState(online, true);
        } else {
            // No window to act on it. Whoever registers next owns this
            // transition, marker included.
            screenMarkerPending = true;
        }

        // The PC is half of what the thermal marker reports, so a login on a
        // hot device says so here — that is the morning where the panel comes
        // up black and the log has to explain why.
        updateThermalMarker();

        // And half of what the night profile reports, for the mirror-image
        // case: a login at 23:00. The window is kept across the offline
        // stretch (see nightWindow), so this is what brings the panel up
        // already dim rather than at full brightness until the first payload
        // lands a minute later.
        updateNight();

        if (online) {
            // Started only now, and stopped below: the data poll exists to
            // keep a visible panel current, and there is no visible panel
            // while the PC is away (T5.1 step 4).
            dataPoller.start();
            // Beside the data poll and for the same reason: the bars exist to
            // move on a lit panel, and the PC captures only while this reads.
            spectrumStream.start();
            bringPanelToFront();
        } else {
            dataPoller.stop();
        spectrumStream.stop();
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
     * The poll loop has booked nothing because the state is dormant — offline
     * and on battery (T5.6). From here the schedule is this service's, and it
     * keeps it in {@code AlarmManager} rather than in a thread, so that the
     * device is free to suspend.
     *
     * <p>Order matters and it is the reverse of the online path: the lock goes
     * <em>before</em> the alarm is armed, because the alarm is what will bring
     * the CPU back and there is nothing to lose by being asleep in between.
     *
     * <p>Called after every dormant probe, not once on entering dormancy, which
     * is what re-arms the alarm for the next one. {@link #setDormant} is what
     * keeps the marker down to one line per transition.
     */
    @Override
    public void onDormant() {
        releaseOfflineWakeLock();
        releaseProbeWakeLock();
        armDormantAlarm();
        setDormant(true);
    }

    /** The marker, on the transition only. */
    private void setDormant(boolean nowDormant) {
        if (dormant == nowDormant) {
            return;
        }
        dormant = nowDormant;
        Log.i(Markers.TAG, Markers.dormant(nowDormant));
    }

    /**
     * Books the sparse probe.
     *
     * <p>{@code setAndAllowWhileIdle}, which is inexact and permitted in Doze.
     * Not {@code setExactAndAllowWhileIdle}: that wants
     * {@code SCHEDULE_EXACT_ALARM} from API 31, and exactness would buy nothing
     * here, because this alarm is the fallback and
     * {@code ACTION_POWER_CONNECTED} is the mechanism.
     *
     * <p>{@code ELAPSED_REALTIME_WAKEUP} rather than {@code RTC_WAKEUP}, for
     * the same reason {@code PcPoller} times its probes on
     * {@code elapsedRealtime}: a clock correction must not move the schedule.
     */
    private void armDormantAlarm() {
        alarms.setAndAllowWhileIdle(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + PcState.DORMANT_ALARM_MS,
                dormantProbeIntent());
    }

    private void cancelDormantAlarm() {
        alarms.cancel(dormantProbeIntent());
    }

    /**
     * The alarm's {@code PendingIntent}, built the same way every time so that
     * {@link #cancelDormantAlarm} matches what {@link #armDormantAlarm}
     * registered — equality here is by action, package and flags, not by
     * object.
     *
     * <p>{@code setPackage}, so this is a package-scoped broadcast rather than
     * an implicit one that any app could see or send.
     */
    private PendingIntent dormantProbeIntent() {
        return PendingIntent.getBroadcast(
                this,
                0,
                new Intent(ACTION_DORMANT_PROBE).setPackage(getPackageName()),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
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

    /** The volume bar's press (T8.4), with invokeAction's checks. */
    public static boolean invokeVolume(int level, DataPoller.ResultListener onResult) {
        PanelService service = instance;
        if (service == null || !Boolean.TRUE.equals(lastOnline)) {
            Log.i(Markers.TAG, Markers.action(Actions.VOLUME, "offline"));
            return false;
        }
        DataPoller poller = service.dataPoller;
        return poller != null && poller.invokeVolume(level, onResult);
    }

    /**
     * One shortcut press, from the Activity's JavaScript bridge (T8.2).
     *
     * <p>Static for the same reason {@link #panelVisible()} is: the Activity
     * and the service are separate components with no lifecycle relationship,
     * and the poller that owns the network lives here.
     *
     * <p>Refused with no request when there is no service or the PC is away.
     * {@link DataPoller#invoke} refuses again on its own side — its executor
     * only exists while online — and the duplication is deliberate: this one
     * answers before a thread is touched, that one is the guarantee.
     *
     * @return false if nothing was sent, so the page can say so immediately
     *         rather than waiting for a result that is not coming
     */
    public static boolean invokeAction(String id, DataPoller.ResultListener onResult) {
        PanelService service = instance;
        if (service == null || !Boolean.TRUE.equals(lastOnline)) {
            Log.i(Markers.TAG, Markers.action(String.valueOf(id), "offline"));
            return false;
        }
        DataPoller poller = service.dataPoller;
        return poller != null && poller.invoke(id, onResult);
    }
}
