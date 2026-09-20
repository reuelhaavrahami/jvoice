package org.jvoice.node;

import static org.junit.Assert.*;
import org.junit.Test;

public class TextChunkerTest {
    @Test public void splitsTokensOnlyAtWordBoundaries() {
        TextChunker c = new TextChunker();
        c.append("Hel", 0); assertEquals("", c.drain(200, false));
        c.append("lo wor", 210); assertEquals("Hello", c.drain(210, false));
        c.append("ld ", 220); assertEquals("", c.drain(220, false));
        assertEquals("world", c.drain(400, false));
    }
    @Test public void finalFlushesLastWordWithoutSpace() {
        TextChunker c = new TextChunker(); c.append("done", 0);
        assertEquals("done", c.drain(0, true)); assertTrue(c.empty());
    }
    @Test public void cancelDiscardsPendingText() {
        TextChunker c = new TextChunker(); c.append("stale ", 0); c.clear();
        assertEquals("", c.drain(1000, true));
    }
    @Test public void punctuationReleasesBeforeTimer() {
        TextChunker c = new TextChunker(); c.append("Hello. Next ", 0);
        assertEquals("Hello.", c.drain(1, false));
        assertEquals("Next", c.drain(200, false));
    }
    @Test(expected = IllegalStateException.class) public void boundsUnbrokenInput() {
        TextChunker c = new TextChunker(); c.append("x".repeat(8193), 0);
    }
}
