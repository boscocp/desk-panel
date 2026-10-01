package dev.bosco.deskpanel;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import org.junit.Test;

public class SpectrumFrameTest {

    private static final String FRAME = "000f10ff0123456789abcdef00000000";

    @Test
    public void aWellFormedFrameIsReturned() {
        assertEquals(FRAME, SpectrumFrame.parse(FRAME));
        assertEquals(FRAME, SpectrumFrame.parse(FRAME + "\r"));
    }

    @Test
    public void anythingThatCouldLeaveTheQuotesIsRefused() {
        assertNull(SpectrumFrame.parse(null));
        assertNull(SpectrumFrame.parse(""));
        assertNull(SpectrumFrame.parse(FRAME.substring(2)));
        assertNull(SpectrumFrame.parse(FRAME + "00"));
        assertNull(SpectrumFrame.parse("000F10FF0123456789ABCDEF00000000"));
        assertNull(SpectrumFrame.parse("')+alert(1)+('0123456789abcdef0"));
        assertNull(SpectrumFrame.parse("000f10ff0123456789abcdef0000000\n"));
        assertNull(SpectrumFrame.parse("000f10ff0123456789abcdef000000 0"));
    }

    @Test
    public void aVolumeLineIsItsLevel() {
        assertEquals(0, SpectrumFrame.parseVolume("v=0"));
        assertEquals(51, SpectrumFrame.parseVolume("v=51"));
        assertEquals(51, SpectrumFrame.parseVolume("v=51\r"));
        assertEquals(100, SpectrumFrame.parseVolume("v=100"));
    }

    @Test
    public void anythingElseIsNotAVolume() {
        String[] refused = {null, "", "v=", "v=101", "v=-1", "v=5.5", "v=0051", "v= 5",
                "V=5", "v=5)", "v=1;alert(1)", "٥", "v=٥", FRAME};
        for (String line : refused) {
            assertEquals(String.valueOf(line), SpectrumFrame.NOT_VOLUME,
                    SpectrumFrame.parseVolume(line));
        }
    }

    @Test
    public void aFrameIsNeverAVolumeAndAVolumeNeverAFrame() {
        assertEquals(SpectrumFrame.NOT_VOLUME, SpectrumFrame.parseVolume(FRAME));
        assertNull(SpectrumFrame.parse("v=51"));
    }
}
