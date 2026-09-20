package org.jvoice.node;

import android.os.Handler;
import android.os.Looper;

/** In-process UI state. Never stores microphone audio or the pairing secret. */
final class NodeState {
    static boolean connected;
    static boolean running;
    static String status = "Ready to connect";
    static String transcript = "Your words will appear here as you speak.";
    static String reply = "Streamed replies will be spoken as they arrive.";
    static Runnable listener;
    static final Handler MAIN = new Handler(Looper.getMainLooper());

    static void update(String text) {
        status = text;
        changed();
    }

    static void changed() {
        if (listener != null) listener.run();
    }
}
