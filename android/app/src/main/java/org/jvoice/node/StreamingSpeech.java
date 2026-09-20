package org.jvoice.node;

import android.content.Context;
import android.os.Bundle;
import android.os.SystemClock;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
import android.speech.tts.Voice;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.function.BiConsumer;

/** Native TTS in short word groups, with generation IDs to ignore cancelled callbacks. */
final class StreamingSpeech {
    private TextToSpeech tts;
    private boolean ready, ended, started, unavailable, closed;
    private String speechId;
    private int count;
    private final Set<String> pending = new HashSet<>();
    private final TextChunker chunker = new TextChunker();
    private final BiConsumer<String, String> event;
    private final Runnable tick = new Runnable() {
        @Override public void run() { flush(); NodeState.MAIN.postDelayed(this, 40); }
    };

    StreamingSpeech(Context context, BiConsumer<String, String> event) {
        this.event = event;
        tts = new TextToSpeech(context, status -> NodeState.MAIN.post(() -> {
            if (closed) return;
            if (status != TextToSpeech.SUCCESS) {
                unavailable = true;
                NodeState.update("Install an Android text-to-speech engine to hear replies");
                fail();
                return;
            }
            int result = tts.setLanguage(Locale.US);
            if (result < TextToSpeech.LANG_AVAILABLE) {
                unavailable = true;
                NodeState.update("Install an English voice in Android speech settings");
                fail();
                return;
            }
            // Prefer offline voices, so the node does not silently send reply text to a cloud engine.
            Voice offline = null;
            if (tts.getVoices() != null) for (Voice voice : tts.getVoices()) {
                if (!voice.isNetworkConnectionRequired() && voice.getLocale().getLanguage().equals("en")
                    && !voice.getFeatures().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED)) {
                    offline = voice;
                    if (voice.getLocale().equals(Locale.US)) break;
                }
            }
            if (offline == null) {
                unavailable = true;
                NodeState.update("Download an offline English TTS voice in Android settings");
                fail();
                return;
            }
            tts.setVoice(offline);
            tts.setAudioAttributes(new android.media.AudioAttributes.Builder()
                .setUsage(android.media.AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH).build());
            ready = true;
            flush();
        }));
        tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
            @Override public void onStart(String id) { NodeState.MAIN.post(() -> {
                if (pending.contains(id) && !started && speechId != null) {
                    started = true;
                    event.accept("playback.started", speechId);
                }
            }); }
            @Override public void onDone(String id) { NodeState.MAIN.post(() -> {
                pending.remove(id); finishIfDone();
            }); }
            @Override public void onError(String id) { NodeState.MAIN.post(() -> {
                if (pending.contains(id)) fail();
            }); }
        });
        NodeState.MAIN.post(tick);
    }

    void start(String id) {
        cancel();
        speechId = id;
        if (unavailable) { fail(); return; }
        ended = started = false;
        NodeState.reply = "";
        NodeState.changed();
    }

    void append(String id, String text) {
        if (!id.equals(speechId) || ended) return;
        try { chunker.append(text, SystemClock.elapsedRealtime()); }
        catch (IllegalStateException e) { fail(); return; }
        NodeState.reply = (NodeState.reply + text);
        if (NodeState.reply.length() > 4000) NodeState.reply = NodeState.reply.substring(NodeState.reply.length() - 4000);
        NodeState.changed();
        flush();
    }

    void end(String id) { if (id.equals(speechId)) { ended = true; flush(); } }
    void cancel(String id) { if (id.equals(speechId)) cancel(); }

    void cancel() {
        String previous = speechId;
        speechId = null;
        chunker.clear(); pending.clear();
        if (tts != null) tts.stop();
        if (previous != null) event.accept("playback.stopped", previous);
    }

    private void fail() {
        String failed = speechId;
        speechId = null;
        chunker.clear(); pending.clear();
        if (tts != null) tts.stop();
        if (failed != null) event.accept("playback.error", failed);
    }

    private void flush() {
        if (!ready || speechId == null) return;
        String text = chunker.drain(SystemClock.elapsedRealtime(), ended);
        if (!text.isEmpty()) {
            if (pending.size() >= 32) { fail(); return; }
            String id = speechId + ":" + count++;
            pending.add(id);
            if (tts.speak(text, TextToSpeech.QUEUE_ADD, new Bundle(), id) == TextToSpeech.ERROR) fail();
        }
        finishIfDone();
    }

    private void finishIfDone() {
        if (speechId != null && ended && chunker.empty() && pending.isEmpty()) {
            String id = speechId; speechId = null;
            event.accept("playback.done", id);
        }
    }

    void close() { closed = true; NodeState.MAIN.removeCallbacks(tick); cancel(); tts.shutdown(); }
}
