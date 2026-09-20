package org.jvoice.node;

/** Keeps subword tokens intact; releases complete words with bounded buffering. */
final class TextChunker {
    private final StringBuilder buffer = new StringBuilder();
    private long since = -1;

    void append(String text, long now) {
        if (buffer.length() + text.length() > 8192) throw new IllegalStateException("Speech input is too fast");
        if (buffer.length() == 0) since = now;
        buffer.append(text);
    }

    String drain(long now, boolean end) {
        if (buffer.length() == 0) return "";
        int boundary = 0;
        boolean punctuation = false;
        for (int i = 0; i < buffer.length(); i++) {
            char c = buffer.charAt(i);
            if (Character.isWhitespace(c)) {
                boundary = i + 1;
                if (i > 0 && ".!?;:".indexOf(buffer.charAt(i - 1)) >= 0) {
                    punctuation = true;
                    break;
                }
                if (boundary >= 100) break;
            }
        }
        if (end) boundary = buffer.length();
        if (boundary == 0 || (!end && !punctuation && boundary < 60 && now - since < 180)) return "";
        String result = buffer.substring(0, boundary).trim();
        buffer.delete(0, boundary);
        since = buffer.length() == 0 ? -1 : now;
        return result;
    }

    boolean empty() { return buffer.length() == 0; }
    void clear() { buffer.setLength(0); since = -1; }
}
