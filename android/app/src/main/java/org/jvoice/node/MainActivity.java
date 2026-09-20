package org.jvoice.node;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.net.URI;

public final class MainActivity extends Activity {
    private static final int BG = Color.rgb(11, 21, 26), CARD = Color.rgb(21, 36, 43);
    private static final int INK = Color.rgb(234, 246, 242), MUTED = Color.rgb(153, 180, 181), MINT = Color.rgb(119, 226, 187);
    private EditText endpoint, node, token, keyword;
    private TextView status, transcript, reply;
    private Button connect, enroll, quiet;
    private SharedPreferences preferences;
    private LinearLayout config;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        preferences = getSharedPreferences("connection", MODE_PRIVATE);
        ScrollView scroll = new ScrollView(this); scroll.setBackgroundColor(BG); scroll.setFillViewport(true);
        LinearLayout page = new LinearLayout(this); page.setOrientation(LinearLayout.VERTICAL); page.setPadding(dp(24), dp(24), dp(24), dp(32));
        scroll.addView(page); setContentView(scroll);
        page.setOnApplyWindowInsetsListener((view, insets) -> {
            page.setPadding(dp(24), dp(24) + insets.getSystemWindowInsetTop(), dp(24), dp(32) + insets.getSystemWindowInsetBottom());
            return insets;
        });
        page.addView(label("J V O I C E   /   N O D E", 12, MINT, true));
        TextView title = label("A voice for\nyour AI network.", 34, INK, true); space(title, 18, 16); page.addView(title);
        TextView subtitle = label("Live words out. Spoken replies in.", 16, MUTED, false); space(subtitle, 0, 24); page.addView(subtitle);
        LinearLayout live = card(page);
        live.addView(label("CONNECTION", 11, MINT, true));
        status = label(NodeState.status, 17, INK, true); space(status, 10, 8); live.addView(status);
        live.addView(label("While connected, microphone audio streams to your host—even before the wake phrase.", 13, MUTED, false));

        config = card(page);
        config.addView(label("YOUR NODE", 11, MINT, true));
        endpoint = field(config, "Host WebSocket URL", preferences.getString("endpoint", "ws://127.0.0.1:8765/v1/node"), false);
        node = field(config, "Node name", preferences.getString("node", "android"), false);
        keyword = field(config, "Wake phrase", preferences.getString("keyword", "hey jarvis"), false);
        token = field(config, "Pairing secret · kept in memory", "", true);
        connect = button(page, "Connect microphone", true, v -> {
            if (NodeState.running) stopService(new Intent(this, VoiceService.class)); else connect();
        });
        enroll = button(page, "Enroll my voice · 5 seconds", false, v -> startService(new Intent(this, VoiceService.class).setAction(VoiceService.ENROLL)));
        quiet = button(page, "Stop speaking", false, v -> startService(new Intent(this, VoiceService.class).setAction(VoiceService.QUIET)));

        LinearLayout heard = card(page); heard.addView(label("LIVE TRANSCRIPT", 11, MINT, true));
        transcript = label(NodeState.transcript, 21, INK, false); space(transcript, 12, 0); heard.addView(transcript);
        LinearLayout answer = card(page); answer.addView(label("VOICE REPLY", 11, MINT, true));
        reply = label(NodeState.reply, 18, INK, false); space(reply, 12, 0); answer.addView(reply);
        TextView note = label("Voice matching helps filter speakers; it is not a secure identity check. A recording can imitate you. Use headphones if speaker echo causes false interruptions.", 12, MUTED, false);
        space(note, 4, 0); page.addView(note);
    }

    private void connect() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 7); return;
        }
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 8);
        }
        String address = endpoint.getText().toString().trim();
        String name = node.getText().toString().trim();
        String wake = keyword.getText().toString().trim();
        String secret = token.getText().toString().trim();
        try {
            URI uri = URI.create(address);
            if (!("wss".equals(uri.getScheme()) || "ws".equals(uri.getScheme())) || uri.getHost() == null
                || !"/v1/node".equals(uri.getPath()) || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null) {
                throw new IllegalArgumentException("Use ws://host:8765/v1/node or wss://host/v1/node");
            }
            if (!name.matches("[A-Za-z0-9_-]{1,64}")) throw new IllegalArgumentException("Use letters, numbers, underscores or hyphens for the node name");
            if (secret.length() < 16) throw new IllegalArgumentException("The pairing secret needs at least 16 characters");
            if (wake.isEmpty()) throw new IllegalArgumentException("Enter a wake phrase");
        } catch (Exception e) { NodeState.update(e.getMessage()); return; }
        preferences.edit().putString("endpoint", address).putString("node", name).putString("keyword", wake).apply();
        Intent intent = new Intent(this, VoiceService.class).setAction(VoiceService.START)
            .putExtra("endpoint", address).putExtra("node", name).putExtra("keyword", wake).putExtra("token", secret);
        startForegroundService(intent);
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == 7) {
            if (results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) connect();
            else NodeState.update("Microphone permission is needed to connect");
        }
    }

    @Override public void onResume() { super.onResume(); NodeState.listener = this::refresh; refresh(); }
    @Override public void onPause() { NodeState.listener = null; super.onPause(); }
    private void refresh() {
        status.setText(NodeState.status); transcript.setText(NodeState.transcript); reply.setText(NodeState.reply);
        connect.setText(NodeState.running ? "Disconnect microphone" : "Connect microphone");
        enroll.setEnabled(NodeState.connected); quiet.setEnabled(NodeState.connected);
        config.setVisibility(NodeState.connected ? View.GONE : View.VISIBLE);
        endpoint.setEnabled(!NodeState.running); node.setEnabled(!NodeState.running); keyword.setEnabled(!NodeState.running); token.setEnabled(!NodeState.running);
    }
    private int dp(int value) { return (int)(value * getResources().getDisplayMetrics().density); }
    private TextView label(String text, int size, int color, boolean bold) {
        TextView view = new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(color);
        view.setLineSpacing(dp(3), 1); if (bold) view.setTypeface(null, Typeface.BOLD); return view;
    }
    private void space(View view, int top, int bottom) {
        LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(-1, -2); p.setMargins(0, dp(top), 0, dp(bottom)); view.setLayoutParams(p);
    }
    private GradientDrawable background(int color) {
        GradientDrawable drawable = new GradientDrawable(); drawable.setColor(color); drawable.setCornerRadius(dp(18)); return drawable;
    }
    private LinearLayout card(LinearLayout parent) {
        LinearLayout layout = new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL); layout.setPadding(dp(20), dp(20), dp(20), dp(20));
        layout.setBackground(background(CARD)); space(layout, 0, 16); parent.addView(layout); return layout;
    }
    private EditText field(LinearLayout parent, String hint, String value, boolean password) {
        TextView caption = label(hint, 12, MUTED, false); space(caption, 16, 2); parent.addView(caption);
        EditText view = new EditText(this); view.setText(value); view.setTextColor(INK); view.setTextSize(15); view.setSingleLine(true);
        view.setId(View.generateViewId()); caption.setLabelFor(view.getId());
        view.setInputType(InputType.TYPE_CLASS_TEXT | (password ? InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS));
        view.setSaveEnabled(!password); if (password) view.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        parent.addView(view); return view;
    }
    private Button button(LinearLayout parent, String text, boolean primary, View.OnClickListener click) {
        Button button = new Button(this); button.setText(text); button.setAllCaps(false); button.setTextColor(primary ? BG : INK);
        button.setBackground(background(primary ? MINT : CARD)); button.setMinHeight(dp(52)); button.setOnClickListener(click);
        space(button, 0, 12); parent.addView(button); return button;
    }
}
