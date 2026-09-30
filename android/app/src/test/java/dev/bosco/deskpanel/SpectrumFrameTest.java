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
}
