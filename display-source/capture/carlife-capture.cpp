/*
 * carlife-capture — capture SailfishOS screen (lipstick-recorder), encode
 * H.264 with x264 and write Annex-B elementary stream to stdout/FIFO.
 */
#include "recorder.h"
#include "convert.h"
#include "shmsource.h"
#include "x264_encoder.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <csignal>
#include <string>
#include <thread>
#include <chrono>
#include <queue>
#include <vector>
#include <mutex>
#include <condition_variable>
#include <atomic>

using namespace imira;

static volatile sig_atomic_t g_running = 1;
static void onSig(int) { g_running = 0; }

static std::queue<std::vector<uint8_t>> g_frames;
static std::mutex g_mtx;
static std::condition_variable g_cv;
static std::atomic<bool> g_quit{false};

int main(int argc, char **argv)
{
    int width = 1920, height = 720, fps = 30, bitrate = 4000000;
    int rotation = 0;
    const char *outPath = nullptr;
    const char *inputMode = "screen";
    for (int i = 1; i < argc - 1; i++) {
        std::string a = argv[i];
        if (a == "--width") width = atoi(argv[++i]);
        else if (a == "--height") height = atoi(argv[++i]);
        else if (a == "--fps") fps = atoi(argv[++i]);
        else if (a == "--bitrate") bitrate = atoi(argv[++i]);
        else if (a == "--rotation") rotation = atoi(argv[++i]);
        else if (a == "--out") outPath = argv[++i];
        else if (a == "--input") inputMode = argv[++i];
    }

    signal(SIGINT, onSig);
    signal(SIGTERM, onSig);
    // Writing to the video FIFO when no reader is attached (e.g. the car
    // disconnected between reconnects) must not kill us with SIGPIPE.
    signal(SIGPIPE, SIG_IGN);

    FILE *out = stdout;
    if (outPath && strcmp(outPath, "-") != 0) {
        out = fopen(outPath, "wb");
        if (!out) {
            fprintf(stderr, "carlife-capture: cannot open %s\n", outPath);
            return 1;
        }
    }

    X264Encoder enc;
    if (!enc.init(width, height, fps, bitrate,
                  [&](const uint8_t *data, size_t size, bool idr) {
                      fwrite(data, 1, size, out);
                      fflush(out);
                  })) {
        fprintf(stderr, "carlife-capture: x264 init failed: %s\n",
                enc.lastError().c_str());
        if (out != stdout) fclose(out);
        return 1;
    }

    FrameConverter conv;
    conv.configure(width, height, false /* I420 */);

    std::thread encThread([&]() {
        while (!g_quit) {
            std::vector<uint8_t> f;
            {
                std::unique_lock<std::mutex> lk(g_mtx);
                g_cv.wait(lk, [] { return !g_frames.empty() || g_quit; });
                if (g_quit && g_frames.empty()) break;
                f = std::move(g_frames.front());
                g_frames.pop();
            }
            if (!enc.encode(f.data(), f.size()))
                fprintf(stderr, "carlife-capture: encode failed: %s\n",
                        enc.lastError().c_str());
        }
    });

    auto onFrame = [&](const uint8_t *pixels, int w, int h, int stride,
                       uint32_t drmFormat, int transform) {
        size_t sz = 0;
        uint8_t *frame = conv.convert(pixels, w, h, stride,
                                      transform == 2, rotation, &sz);
        if (frame) {
            {
                std::lock_guard<std::mutex> lk(g_mtx);
                if (g_frames.size() < 8)
                    g_frames.emplace(frame, frame + sz);
            }
            free(frame);
            g_cv.notify_one();
        }
    };

    bool sourceOk = false;
    if (strcmp(inputMode, "shm") == 0) {
        ShmFrameSource shmSrc;
        sourceOk = shmSrc.start(fps, onFrame);
        if (!sourceOk) {
            fprintf(stderr, "carlife-capture: shm source start failed\n");
        } else {
            fprintf(stderr, "carlife-capture: shm input mode\n");
            while (g_running)
                std::this_thread::sleep_for(std::chrono::milliseconds(400));
        }
        shmSrc.stop();
    } else {
        ScreenRecorder rec;
        sourceOk = rec.start(onFrame);
        if (!sourceOk) {
            fprintf(stderr, "carlife-capture: recorder start failed\n");
        } else {
            fprintf(stderr, "carlife-capture: streaming %dx%d@%d rot=%d -> %s\n",
                    width, height, fps, rotation, outPath ? outPath : "stdout");
            while (g_running) {
                rec.requestRepaint();
                std::this_thread::sleep_for(std::chrono::milliseconds(400));
            }
        }
        rec.stop();
    }

    if (!sourceOk) {
        g_quit = true;
        g_cv.notify_all();
        encThread.join();
        enc.stop();
        if (out != stdout) fclose(out);
        return 1;
    }

    g_quit = true;
    g_cv.notify_all();
    encThread.join();
    enc.stop();
    if (out != stdout) fclose(out);
    return 0;
}