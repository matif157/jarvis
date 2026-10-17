package ai.jarvis.assistant.voice;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.Voice;
import android.webkit.WebView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Voice bridge between the Python app (Chaquopy) and Android's speech stack.
 *
 * <p>Three capabilities, all JSON-in/JSON-out so Python never touches Java
 * types: text-to-speech ({@link #speak}), on-device recognition via the
 * system {@link SpeechRecognizer} ({@link #recognize}, blocks until a
 * result), and raw WAV capture for cloud transcription ({@link #record}).
 * The Activity attaches an application context via {@link #attach}.
 */
public final class VoiceBridge {

    private static final Object LOCK = new Object();
    private static final String[] MIC_PERMISSION = {Manifest.permission.RECORD_AUDIO};

    private static Context appContext;
    private static TextToSpeech tts;
    private static boolean ttsReady;
    private static String pendingSpeak;
    private static float pendingRate = 1.0f;

    private VoiceBridge() {
    }

    /** Called once from MainActivity so the bridges have an app context. */
    public static void attach(Context context) {
        synchronized (LOCK) {
            if (appContext == null) {
                appContext = context.getApplicationContext();
            }
            if (tts == null && appContext != null) {
                tts = new TextToSpeech(appContext, status -> {
                    synchronized (LOCK) {
                        ttsReady = status == TextToSpeech.SUCCESS;
                        if (ttsReady && pendingSpeak != null) {
                            String text = pendingSpeak;
                            float rate = pendingRate;
                            pendingSpeak = null;
                            speakLocked(text, rate, null);
                        }
                    }
                });
            }
        }
    }

    private static boolean micGranted() {
        return appContext != null
                && appContext.checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                        == PackageManager.PERMISSION_GRANTED;
    }

    /** {"text": ..., "rate": optional, "language": optional} -> {ok, provider} */
    public static String speak(String requestJson) {
        try {
            JSONObject request = new JSONObject(requestJson);
            String text = request.optString("text", "").trim();
            if (text.isEmpty()) {
                return error("text required");
            }
            float rate = (float) request.optDouble("rate", 1.0);
            if (!(rate > 0.25f && rate < 4.0f)) {
                rate = 1.0f;
            }
            String language = request.optString("language", null);
            synchronized (LOCK) {
                if (tts == null) {
                    return error("text-to-speech is not initialised");
                }
                if (!ttsReady) {
                    pendingSpeak = text;
                    pendingRate = rate;
                    return ok().put("queued", true).toString();
                }
                speakLocked(text, rate, language);
            }
            return ok().put("provider", "android_tts").toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    private static void speakLocked(String text, float rate, String language) {
        try {
            tts.setSpeechRate(rate);
            if (language != null && !language.isEmpty()) {
                Locale locale = language.contains("-") || language.contains("_")
                        ? Locale.forLanguageTag(language.replace('_', '-'))
                        : new Locale(language);
                tts.setLanguage(locale);
            }
            tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "jarvis-" + System.nanoTime());
        } catch (Throwable ignored) {
            // best effort: an unavailable voice simply produces no audio
        }
    }

    /** Stop any ongoing utterance. */
    public static String stopSpeak() {
        synchronized (LOCK) {
            pendingSpeak = null;
            if (tts != null) {
                try {
                    tts.stop();
                } catch (Throwable ignored) {
                    // best effort
                }
            }
        }
        return ok().toString();
    }

    /** {"language": optional} -> {ok, voices: [names]} */
    public static String voices(String requestJson) {
        try {
            JSONObject request = new JSONObject(
                    requestJson == null || requestJson.isEmpty() ? "{}" : requestJson);
            String language = request.optString("language", "");
            List<String> names = new ArrayList<>();
            synchronized (LOCK) {
                if (tts != null && ttsReady) {
                    try {
                        for (Voice voice : tts.getVoices()) {
                            String name = voice.getName();
                            if (!language.isEmpty() && voice.getLocale() != null) {
                                String tag = voice.getLocale().toLanguageTag();
                                if (!tag.toLowerCase(Locale.ROOT)
                                        .startsWith(language.toLowerCase(Locale.ROOT))) {
                                    continue;
                                }
                            }
                            names.add(name);
                            if (names.size() >= 100) {
                                break;
                            }
                        }
                    } catch (Throwable ignored) {
                        // older OEM engines may not implement getVoices()
                    }
                }
            }
            JSONArray array = new JSONArray(names);
            return ok().put("voices", array).toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    /** {ok, tts:{...}, mic:{granted}} - used by /api/voice/status. */
    public static String status() {
        JSONObject out = ok();
        try {
            synchronized (LOCK) {
                JSONObject ttsInfo = new JSONObject();
                ttsInfo.put("ready", ttsReady);
                ttsInfo.put("initialised", tts != null);
                boolean speaking = false;
                if (tts != null && ttsReady) {
                    try {
                        speaking = tts.isSpeaking();
                    } catch (Throwable ignored) {
                        // best effort
                    }
                }
                ttsInfo.put("speaking", speaking);
                out.put("tts", ttsInfo);
            }
            out.put("mic", new JSONObject().put("granted", micGranted()));
        } catch (Throwable t) {
            return error(describe(t));
        }
        return out.toString();
    }

    /**
     * {"language": "ur"|"en"|..., "timeout_ms": N} -> {ok, text} / error.
     *
     * <p>Blocks the calling (worker) thread: the recognizer itself runs on the
     * main looper, as required by the Android framework.
     */
    public static String recognize(String requestJson) {
        try {
            JSONObject request = new JSONObject(
                    requestJson == null || requestJson.isEmpty() ? "{}" : requestJson);
            String language = request.optString("language", "");
            if (language.isEmpty()) {
                language = "ur-PK";
            }
            long timeoutMs = request.optLong("timeout_ms", 20000L);
            if (timeoutMs < 5000L) {
                timeoutMs = 5000L;
            }
            if (timeoutMs > 60000L) {
                timeoutMs = 60000L;
            }
            final long finalTimeoutMs = timeoutMs;
            if (!micGranted()) {
                return error("microphone permission not granted");
            }

            final java.util.concurrent.CountDownLatch latch =
                    new java.util.concurrent.CountDownLatch(1);
            final String[] payload = new String[1];
            final String[] failure = new String[1];
            final SpeechRecognizer[] holder = new SpeechRecognizer[1];
            final String finalLanguage = language;

            Runnable start = () -> {
                try {
                    SpeechRecognizer recognizer =
                            SpeechRecognizer.createSpeechRecognizer(appContext);
                    holder[0] = recognizer;
                    recognizer.setRecognitionListener(new RecognitionListener() {
                        @Override
                        public void onReadyForSpeech(Bundle params) {
                        }

                        @Override
                        public void onBeginningOfSpeech() {
                        }

                        @Override
                        public void onRmsChanged(float rmsdB) {
                        }

                        @Override
                        public void onBufferReceived(byte[] buffer) {
                        }

                        @Override
                        public void onEndOfSpeech() {
                        }

                        @Override
                        public void onError(int error) {
                            failure[0] = "speech recognition failed (code " + error
                                    + isNetworkError(error) + ")";
                            latch.countDown();
                        }

                        @Override
                        public void onResults(Bundle results) {
                            try {
                                ArrayList<String> list = results.getStringArrayList(
                                        SpeechRecognizer.RESULTS_RECOGNITION);
                                String text = (list == null || list.isEmpty())
                                        ? "" : list.get(0);
                                payload[0] = text;
                            } catch (Throwable t) {
                                payload[0] = "";
                            }
                            latch.countDown();
                        }

                        @Override
                        public void onPartialResults(Bundle partialResults) {
                        }

                        @Override
                        public void onEvent(int eventType, Bundle params) {
                        }

                        private String isNetworkError(int code) {
                            return code == SpeechRecognizer.ERROR_NETWORK
                                    ? " - check your connection or use cloud mode" : "";
                        }
                    });

                    Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                            RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                    intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, finalLanguage);
                    intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
                    intent.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false);
                    intent.putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE,
                            appContext.getPackageName());
                    recognizer.startListening(intent);

                    new Handler(Looper.getMainLooper()).postDelayed(() -> {
                        if (latch.getCount() > 0) {
                            failure[0] = "speech recognition timed out";
                            latch.countDown();
                        }
                    }, finalTimeoutMs);
                } catch (Throwable t) {
                    failure[0] = describe(t);
                    latch.countDown();
                }
            };
            new Handler(Looper.getMainLooper()).post(start);

            latch.await(finalTimeoutMs + 5000L, java.util.concurrent.TimeUnit.MILLISECONDS);

            new Handler(Looper.getMainLooper()).post(() -> {
                SpeechRecognizer recognizer = holder[0];
                if (recognizer != null) {
                    try {
                        recognizer.cancel();
                        recognizer.destroy();
                    } catch (Throwable ignored) {
                        // best effort
                    }
                }
            });

            if (failure[0] != null) {
                return error(failure[0]);
            }
            String result = payload[0];
            if (result == null) {
                return error("speech recognition timed out");
            }
            if (result.isEmpty()) {
                return error("nothing was heard");
            }
            return ok().put("text", result.trim()).toString();
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            return error("interrupted");
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    /**
     * {"seconds": 1..30} -> {ok, path, duration_ms, sample_rate} - captures
     * mono 16-bit PCM and writes a WAV file for cloud transcription.
     */
    public static String record(String requestJson) {
        try {
            JSONObject request = new JSONObject(
                    requestJson == null || requestJson.isEmpty() ? "{}" : requestJson);
            int seconds = request.optInt("seconds", 8);
            if (seconds < 1) {
                seconds = 1;
            }
            if (seconds > 30) {
                seconds = 30;
            }
            if (!micGranted()) {
                return error("microphone permission not granted");
            }

            int rate = pickSampleRate();
            int minBuffer = AudioRecord.getMinBufferSize(rate,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (minBuffer <= 0) {
                return error("audio recording is not supported on this device");
            }
            AudioRecord recorder;
            try {
                recorder = new AudioRecord(MediaRecorder.AudioSource.MIC, rate,
                        AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                        Math.max(minBuffer, rate));
            } catch (Throwable t) {
                return error("cannot open microphone: " + describe(t));
            }
            if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
                recorder.release();
                return error("cannot open microphone (state "
                        + recorder.getState() + ")");
            }

            File dir = new File(appContext.getFilesDir(), "voice");
            if (!dir.exists()) {
                //noinspection ResultOfMethodCallIgnored
                dir.mkdirs();
            }
            File wav = new File(dir, "capture-" + System.currentTimeMillis() + ".wav");

            long started = System.currentTimeMillis();
            long written = 0;
            try (FileOutputStream fos = new FileOutputStream(wav);
                 DataOutputStream out = new DataOutputStream(fos)) {
                writeWavHeader(out, rate, 1, 16, 0);
                recorder.startRecording();
                byte[] buffer = new byte[Math.max(minBuffer, 4096)];
                long targetBytes = (long) seconds * rate * 2L;
                while (written < targetBytes) {
                    int read = recorder.read(buffer, 0, buffer.length);
                    if (read <= 0) {
                        break;
                    }
                    out.write(buffer, 0, read);
                    written += read;
                }
            } finally {
                try {
                    recorder.stop();
                } catch (Throwable ignored) {
                    // best effort
                }
                recorder.release();
            }
            patchWavHeader(wav, buildWavHeader(rate, 1, 16, written));

            JSONObject ok = ok();
            ok.put("path", wav.getAbsolutePath());
            ok.put("duration_ms", System.currentTimeMillis() - started);
            ok.put("sample_rate", rate);
            ok.put("bytes", wav.length());
            return ok.toString();
        } catch (Throwable t) {
            return error(describe(t));
        }
    }

    private static int pickSampleRate() {
        int[] candidates = {16000, 44100, 48000, 8000};
        for (int rate : candidates) {
            int min = AudioRecord.getMinBufferSize(rate,
                    AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
            if (min > 0) {
                return rate;
            }
        }
        return 16000;
    }

    private static byte[] buildWavHeader(int rate, int channels, int bits, long dataBytes) {
        long byteRate = (long) rate * channels * bits / 8;
        long total = 36 + dataBytes;
        byte[] h = new byte[44];
        writeFourCC(h, 0, "RIFF");
        writeLe32(h, 4, (int) total);
        writeFourCC(h, 8, "WAVE");
        writeFourCC(h, 12, "fmt ");
        writeLe32(h, 16, 16);
        h[20] = 1; // PCM
        h[22] = (byte) channels;
        writeLe32(h, 24, rate);
        writeLe32(h, 28, (int) byteRate);
        h[32] = (byte) (channels * bits / 8);
        h[34] = (byte) bits;
        writeFourCC(h, 36, "data");
        writeLe32(h, 40, (int) dataBytes);
        return h;
    }

    private static void writeWavHeader(DataOutputStream out, int rate, int channels,
                                       int bits, long dataBytes) throws Exception {
        out.write(buildWavHeader(rate, channels, bits, dataBytes));
    }

    private static void patchWavHeader(File wav, byte[] header) throws Exception {
        try (java.io.RandomAccessFile raf = new java.io.RandomAccessFile(wav, "rw")) {
            raf.seek(0);
            raf.write(header);
        }
    }

    private static void writeFourCC(byte[] target, int offset, String value) {
        for (int i = 0; i < 4; i++) {
            target[offset + i] = (byte) value.charAt(i);
        }
    }

    private static void writeLe32(byte[] target, int offset, int value) {
        target[offset] = (byte) (value & 0xFF);
        target[offset + 1] = (byte) ((value >> 8) & 0xFF);
        target[offset + 2] = (byte) ((value >> 16) & 0xFF);
        target[offset + 3] = (byte) ((value >> 24) & 0xFF);
    }

    private static JSONObject ok() {
        try {
            return new JSONObject().put("ok", true);
        } catch (Throwable t) {
            return new JSONObject();
        }
    }

    private static String error(String message) {
        JSONObject out = new JSONObject();
        try {
            out.put("ok", false);
            out.put("error", message);
        } catch (Throwable t) {
            return "{\"ok\":false,\"error\":\"bridge error\"}";
        }
        return out.toString();
    }

    private static String describe(Throwable t) {
        String message = t.getMessage();
        String name = t.getClass().getSimpleName();
        if (message == null || message.isEmpty()) {
            return name;
        }
        if (message.length() > 200) {
            message = message.substring(0, 200);
        }
        return name + ": " + message;
    }
}
