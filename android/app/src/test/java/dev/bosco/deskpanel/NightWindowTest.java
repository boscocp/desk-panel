package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Calendar;
import java.util.TimeZone;

/**
 * The window that dims the backlight, on the JVM (T6.4).
 *
 * <p>The shipped default wraps midnight — 22:00 to 07:00 — so the wrapping
 * branch is the ordinary path and not the exotic one, which is the opposite of
 * how a predicate like this usually gets tested. Most of the assertions below
 * are about it.
 *
 * <p>The other half is parity: {@code isNight} in {@code web/js/format.js}
 * answers the same question for the glow, and the two implementations are
 * only worth having if they agree. Every bound {@code web/test/format.test.js}
 * feeds that one is fed to this one.
 */
public class NightWindowTest {

    /** A payload carrying exactly the two bounds under test and nothing else. */
    private static String payload(String start, String end) {
        return "{\"night\":{\"start\":" + start + ",\"end\":" + end + "}}";
    }

    private static String quoted(String start, String end) {
        return payload("\"" + start + "\"", "\"" + end + "\"");
    }

    private static int at(int hour, int minute) {
        return hour * 60 + minute;
    }

    // --- the wrap, which is what is wrong first ---------------------------

    @Test
    public void theShippedWindowCoversTheHoursEitherSideOfMidnight() {
        NightWindow night = NightWindow.parse(quoted("22:00", "07:00"));
        assertNotNull(night);
        assertTrue(night.covers(at(22, 0)));
        assertTrue(night.covers(at(23, 59)));
        assertTrue(night.covers(at(0, 0)));
        assertTrue(night.covers(at(3, 30)));
        assertTrue(night.covers(at(6, 59)));
    }

    @Test
    public void theShippedWindowLeavesTheWorkingDayAlone() {
        NightWindow night = NightWindow.parse(quoted("22:00", "07:00"));
        assertFalse(night.covers(at(7, 0)));
        assertFalse(night.covers(at(12, 0)));
        assertFalse(night.covers(at(21, 59)));
    }

    /**
     * The end is exclusive and the start is inclusive, both ways round. An
     * implementation that used {@code <=} at the end leaves the panel dim for
     * one minute after the alarm goes off, which is the kind of thing nobody
     * ever reports and everybody notices.
     */
    @Test
    public void theBoundsAreHalfOpenOnBothSidesOfTheWrap() {
        NightWindow wrapping = NightWindow.parse(quoted("22:00", "07:00"));
        assertTrue(wrapping.covers(at(22, 0)));
        assertFalse(wrapping.covers(at(7, 0)));

        NightWindow plain = NightWindow.parse(quoted("13:00", "14:00"));
        assertTrue(plain.covers(at(13, 0)));
        assertFalse(plain.covers(at(14, 0)));
    }

    @Test
    public void aWindowInsideOneDayDoesNotWrap() {
        NightWindow night = NightWindow.parse(quoted("22:00", "23:00"));
        assertTrue(night.covers(at(22, 30)));
        assertFalse(night.covers(at(23, 0)));
        assertFalse(night.covers(at(2, 0)));
    }

    // --- the bounds themselves --------------------------------------------

    @Test
    public void minutesAreHonouredRatherThanRoundedToTheHour() {
        NightWindow night = NightWindow.parse(quoted("22:30", "07:00"));
        assertFalse(night.covers(at(22, 15)));
        assertTrue(night.covers(at(22, 30)));
    }

    @Test
    public void aBareHourIsAcceptedBecauseFormatJsAcceptsOne() {
        NightWindow night = NightWindow.parse(payload("22", "6"));
        assertNotNull(night);
        assertTrue(night.covers(at(23, 0)));
        assertFalse(night.covers(at(6, 0)));
    }

    @Test
    public void aSingleDigitHourIsATimeAndASingleDigitMinuteIsNot() {
        assertNotNull(NightWindow.parse(quoted("9:30", "7:00")));
        // "22:5" would be read as 22:05 by Integer.parseInt, which is a
        // quarter of an hour of dimming nobody wrote down.
        assertNull(NightWindow.parse(quoted("22:5", "07:00")));
    }

    /**
     * Every malformed shape leaves the panel in its day profile, because a
     * typo in a file on the PC must cost the dimming and never the panel.
     */
    @Test
    public void anythingThatIsNotATimeIsNoWindowAtAll() {
        assertNull(NightWindow.parse(null));
        assertNull(NightWindow.parse("not json at all"));
        assertNull(NightWindow.parse("{\"quotes\":[]}"));
        assertNull(NightWindow.parse("{\"night\":{}}"));
        assertNull(NightWindow.parse(quoted("", "07:00")));
        assertNull(NightWindow.parse(quoted("22:00", "")));
        assertNull(NightWindow.parse(quoted("24:00", "07:00")));
        assertNull(NightWindow.parse(quoted("22:60", "07:00")));
        assertNull(NightWindow.parse(quoted("22.00", "07:00")));
        assertNull(NightWindow.parse(quoted("22:00:00", "07:00")));
        assertNull(NightWindow.parse(payload("24", "6")));
        assertNull(NightWindow.parse(payload("true", "false")));
    }

    /**
     * {@code Integer.parseInt} reads a leading plus and every Unicode decimal
     * digit there is, so a bound of "+2:00" or of Arabic-Indic digits would
     * parse by accident and dim the panel at a time nobody wrote down.
     */
    @Test
    public void aBoundIsAsciiDigitsAndNothingElse() {
        assertNull(NightWindow.parse(quoted("+2:00", "07:00")));
        assertNull(NightWindow.parse(quoted("-2:00", "07:00")));
        assertNull(NightWindow.parse(quoted("٢٢:00", "07:00")));
    }

    /**
     * Two bounds at the same instant describe either no night or a permanent
     * one, and there is no way to tell which was meant. Day, like every other
     * unusable config. {@code isNight} answers the same.
     */
    @Test
    public void aZeroLengthWindowIsNotAPermanentNight() {
        assertNull(NightWindow.parse(quoted("22:00", "22:00")));
    }

    @Test
    public void surroundingWhitespaceIsToleratedTheWayFormatJsToleratesIt() {
        NightWindow night = NightWindow.parse(quoted(" 22:00 ", " 07:00 "));
        assertNotNull(night);
        assertTrue(night.covers(at(23, 0)));
    }

    // --- the clock --------------------------------------------------------

    /**
     * The calendar is the caller's, which is the whole reason the wrap above
     * can be tested at all: a predicate that read the clock itself could only
     * be exercised at midnight.
     */
    @Test
    public void minuteOfDayIsReadOffTheCalendarItIsGiven() {
        Calendar c = Calendar.getInstance(TimeZone.getTimeZone("UTC"));
        c.set(2026, Calendar.FEBRUARY, 23, 22, 30, 0);
        assertEquals(at(22, 30), NightWindow.minuteOfDay(c));

        c.set(2026, Calendar.FEBRUARY, 24, 0, 0, 0);
        assertEquals(0, NightWindow.minuteOfDay(c));
    }

    /**
     * The one property the two readers have to share, asserted as a property
     * rather than as a list: over a whole day at one-minute resolution, the
     * shipped window is night for exactly the 540 minutes between 22:00 and
     * 07:00. {@code web/test/format.test.js} makes the same count.
     */
    @Test
    public void theShippedWindowIsExactlyNineHoursLong() {
        NightWindow night = NightWindow.parse(quoted("22:00", "07:00"));
        int covered = 0;
        for (int minute = 0; minute < 24 * 60; minute += 1) {
            if (night.covers(minute)) {
                covered += 1;
            }
        }
        assertEquals(9 * 60, covered);
    }
}
