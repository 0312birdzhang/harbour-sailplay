/*
 * x264_encoder.h — software H.264 encoder via x264.
 */
#ifndef X264_ENCODER_H
#define X264_ENCODER_H

#include <cstdint>
#include <cstddef>
#include <functional>
#include <string>

struct x264_t;
struct x264_picture_t;

class X264Encoder {
public:
    using OutputCallback = std::function<void(const uint8_t *data, size_t size,
                                              bool idr)>;

    X264Encoder() = default;
    ~X264Encoder() { stop(); }
    X264Encoder(const X264Encoder &) = delete;
    X264Encoder &operator=(const X264Encoder &) = delete;

    // Encode I420 frames.
    bool init(int width, int height, int fps, int bitrate,
              const OutputCallback &cb);
    bool encode(const uint8_t *i420, size_t size);
    void stop();

    const std::string &lastError() const { return m_error; }

private:
    x264_t *m_enc = nullptr;
    x264_picture_t *m_pic = nullptr;
    OutputCallback m_cb;
    long long m_pts = 0;
    int m_width = 0, m_height = 0;
    std::string m_error;
};

#endif