package org.jvoice.node;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.media.audiofx.AcousticEchoCanceler;
import android.media.audiofx.NoiseSuppressor;
import android.os.IBinder;
import org.json.JSONObject;
import java.util.concurrent.TimeUnit;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

public final class VoiceService extends Service {
    static final String START = "org.jvoice.START", STOP = "org.jvoice.STOP";
    static final String ENROLL = "org.jvoice.ENROLL", QUIET = "org.jvoice.QUIET";
    private OkHttpClient client;
    private WebSocket socket;
    private StreamingSpeech speech;
    private volatile boolean recording;
    private volatile AudioRecord recorder;
    private Thread capture;
    private AudioManager audioManager;
    private int previousAudioMode;
    private boolean destroyed;
    private android.os.PowerManager.WakeLock wakeLock;
    private final Runnable handshakeTimeout = () -> fail("Connection timed out waiting for the host");
    private final Runnable renewWakeLock = new Runnable() {
        @Override public void run() {
            if (!destroyed && NodeState.running) {
                wakeLock.acquire(10 * 60 * 1000L);
                NodeState.MAIN.postDelayed(this, 5 * 60 * 1000L);
            }
        }
    };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public void onCreate() {
        super.onCreate();
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel("voice", "Voice connection", NotificationManager.IMPORTANCE_LOW));
        Intent launch = new Intent(this, MainActivity.class);
        PendingIntent open = PendingIntent.getActivity(this, 0, launch, PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(this, 1, new Intent(this, VoiceService.class).setAction(STOP), PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, "voice")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("JVoice microphone is active")
            .setContentText("Sending audio to your configured speech host")
            .setContentIntent(open).setOngoing(true).addAction(android.R.drawable.ic_media_pause, "Disconnect", stop).build();
        startForeground(1, notification);
        wakeLock = getSystemService(android.os.PowerManager.class).newWakeLock(
            android.os.PowerManager.PARTIAL_WAKE_LOCK, "JVoice:microphone");
        wakeLock.setReferenceCounted(false);
        wakeLock.acquire(10 * 60 * 1000L);
        NodeState.MAIN.postDelayed(renewWakeLock, 5 * 60 * 1000L);
        audioManager = getSystemService(AudioManager.class);
        previousAudioMode = audioManager.getMode();
        audioManager.setMode(AudioManager.MODE_IN_COMMUNICATION);
        speech = new StreamingSpeech(this, this::playbackEvent);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null || STOP.equals(intent.getAction())) { stopSelf(); return START_NOT_STICKY; }
        if (ENROLL.equals(intent.getAction())) {
            if (NodeState.connected) { speech.cancel(); send(event("enroll.start")); }
            return START_NOT_STICKY;
        }
        if (QUIET.equals(intent.getAction())) { speech.cancel(); return START_NOT_STICKY; }
        if (socket != null) return START_NOT_STICKY;
        NodeState.running = true;
        NodeState.update("Connecting to your speech host…");
        NodeState.MAIN.postDelayed(handshakeTimeout, 10000);
        String endpoint = intent.getStringExtra("endpoint");
        String token = intent.getStringExtra("token");
        JSONObject hello = event("hello");
        put(hello, "node_id", intent.getStringExtra("node"));
        put(hello, "keyword", intent.getStringExtra("keyword"));
        put(hello, "sample_rate", 16000);
        try {
            client = new OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS)
                .connectTimeout(10, TimeUnit.SECONDS).build();
            socket = client.newWebSocket(new Request.Builder().url(endpoint)
                .header("Authorization", "Bearer " + token).build(), new WebSocketListener() {
                @Override public void onOpen(WebSocket ws, Response response) { ws.send(hello.toString()); }
                @Override public void onMessage(WebSocket ws, String text) {
                    NodeState.MAIN.post(() -> { if (!destroyed) receive(text); });
                }
                @Override public void onFailure(WebSocket ws, Throwable error, Response response) {
                    NodeState.MAIN.post(() -> fail("Connection failed: " + error.getMessage()));
                }
                @Override public void onClosing(WebSocket ws, int code, String reason) {
                    ws.close(code, reason);
                    NodeState.MAIN.post(() -> fail("Disconnected: " + reason));
                }
            });
        } catch (Exception e) { fail("Unable to connect: " + e.getMessage()); }
        return START_NOT_STICKY;
    }

    private void receive(String raw) {
        try {
            JSONObject event = new JSONObject(raw);
            if (event.getInt("v") != 1) throw new IllegalArgumentException("Unsupported host version");
            String id = event.optString("speech_id");
            switch (event.getString("type")) {
                case "ready":
                    NodeState.MAIN.removeCallbacks(handshakeTimeout);
                    NodeState.connected = true;
                    NodeState.update(event.optBoolean("enrolled") ? "Listening for your wake phrase" : "Connected · enroll your voice to begin");
                    startCapture(); break;
                case "enrollment.started": NodeState.update("Enrolling · speak naturally for five seconds"); break;
                case "enrollment.complete": NodeState.update("Voice enrolled · say your wake phrase"); break;
                case "enrollment.required": NodeState.update("Enroll your voice to enable recognition"); break;
                case "speaker.rejected": NodeState.update("Voice did not match · try again"); break;
                case "session.activated": speech.cancel(); NodeState.update("Voice verified · streaming your words"); break;
                case "transcript":
                    NodeState.transcript = event.getString("text");
                    if (event.getBoolean("final")) NodeState.update("Listening · conversation stays awake for 10 seconds");
                    else NodeState.changed();
                    break;
                case "speak.start": speech.start(id); break;
                case "speak.text": speech.append(id, event.getString("text")); break;
                case "speak.end": speech.end(id); break;
                case "speak.cancel": speech.cancel(id); break;
                case "error": NodeState.update(event.optString("detail", "Host error")); break;
                default: break;
            }
        } catch (Exception e) { fail("Host protocol error: " + e.getMessage()); }
    }

    private void startCapture() {
        if (recording) return;
        recording = true;
        capture = new Thread(() -> {
            AcousticEchoCanceler echo = null;
            NoiseSuppressor noise = null;
            AudioRecord audio = null;
            try {
                if (checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    throw new SecurityException("Microphone permission was revoked");
                }
                int buffer = Math.max(6400, AudioRecord.getMinBufferSize(16000,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT));
                audio = new AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,
                    16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, buffer);
                recorder = audio;
                if (audio.getState() != AudioRecord.STATE_INITIALIZED) throw new IllegalStateException("Microphone unavailable");
                if (AcousticEchoCanceler.isAvailable()) {
                    echo = AcousticEchoCanceler.create(audio.getAudioSessionId());
                    if (echo != null) echo.setEnabled(true);
                }
                if (NoiseSuppressor.isAvailable()) {
                    noise = NoiseSuppressor.create(audio.getAudioSessionId());
                    if (noise != null) noise.setEnabled(true);
                }
                audio.startRecording();
                byte[] frame = new byte[640]; // 20 ms, mono PCM16 little endian.
                while (recording) {
                    int count = audio.read(frame, 0, frame.length, AudioRecord.READ_BLOCKING);
                    if (!recording) break;
                    if (count <= 0 || count % 2 != 0) throw new IllegalStateException("Microphone read failed");
                    // Do not replay stale audio after congestion; stop visibly and let the user reconnect.
                    if (socket.queueSize() > 32000 || !socket.send(ByteString.of(frame, 0, count))) {
                        throw new IllegalStateException("Network cannot keep up with live audio");
                    }
                }
            } catch (Exception e) {
                if (recording) NodeState.MAIN.post(() -> fail("Audio stopped: " + e.getMessage()));
            } finally {
                if (echo != null) echo.release();
                if (noise != null) noise.release();
                if (audio != null) { try { audio.stop(); } catch (Exception ignored) { } audio.release(); }
                recorder = null;
            }
        }, "jvoice-capture");
        capture.start();
    }

    private void playbackEvent(String kind, String id) {
        JSONObject object = event(kind); put(object, "speech_id", id); send(object);
    }
    private void send(JSONObject object) { if (socket != null) socket.send(object.toString()); }
    private static JSONObject event(String kind) {
        JSONObject obj = new JSONObject(); put(obj, "v", 1); put(obj, "type", kind); return obj;
    }
    private static void put(JSONObject obj, String key, Object value) {
        try { obj.put(key, value); } catch (Exception e) { throw new IllegalArgumentException(e); }
    }
    private void fail(String detail) { if (!destroyed) { NodeState.update(detail); stopSelf(); } }

    @Override public void onDestroy() {
        destroyed = true;
        NodeState.MAIN.removeCallbacks(handshakeTimeout);
        NodeState.MAIN.removeCallbacks(renewWakeLock);
        recording = false;
        AudioRecord audio = recorder;
        if (audio != null) try { audio.stop(); } catch (Exception ignored) { }
        speech.close();
        if (socket != null) socket.close(1000, "Node disconnected");
        if (client != null) { client.dispatcher().executorService().shutdown(); client.connectionPool().evictAll(); }
        audioManager.setMode(previousAudioMode);
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        NodeState.connected = NodeState.running = false;
        if (!NodeState.status.startsWith("Connection") && !NodeState.status.startsWith("Audio") && !NodeState.status.startsWith("Host") && !NodeState.status.startsWith("Disconnected")) {
            NodeState.status = "Disconnected · microphone off";
        }
        NodeState.changed();
        super.onDestroy();
    }
}
