/*
 * harbour-imira — RGBA -> YUV420 conversion (BT.601 limited range),
 * nearest-neighbour scaling with letterbox and optional 90/270 degree
 * rotation (lipstick always delivers the native portrait framebuffer,
 * landscape content arrives rotated inside it). Plain C++; fast enough
 * for 720p30 on the Xperia 10 III.
 */
#include "convert.h"

#include <cstdlib>
#include <cstring>
#if defined(__aarch64__)
#include <arm_neon.h>
#endif

namespace imira {

void FrameConverter::configure(int dstWidth, int dstHeight, bool nv12)
{
    m_dw = dstWidth & ~1;
    m_dh = dstHeight & ~1;
    m_nv12 = nv12;
    m_lastSrcW = m_lastSrcH = 0;
    m_lastRot = -1;
}

void FrameConverter::updateMaps(int srcW, int srcH, int rot)
{
    // Effective content size after rotation.
    int cw = (rot == 90 || rot == 270) ? srcH : srcW;
    int ch = (rot == 90 || rot == 270) ? srcW : srcH;
    int boxW = m_dw;
    int boxH = (int)((int64_t)m_dw * ch / cw);
    if (boxH > m_dh) {
        boxH = m_dh;
        boxW = (int)((int64_t)m_dh * cw / ch);
    }
    m_boxW = boxW & ~1;
    m_boxH = boxH & ~1;
    m_boxX = ((m_dw - m_boxW) / 2) & ~1;
    m_boxY = ((m_dh - m_boxH) / 2) & ~1;
    m_lastSrcW = srcW;
    m_lastSrcH = srcH;
    m_lastRot = rot;
}

uint8_t *FrameConverter::convert(const uint8_t *src, int srcW, int srcH,
                                 int srcStride, bool yInverted, int rotation,
                                 size_t *outSize)
{
    if (srcW != m_lastSrcW || srcH != m_lastSrcH || rotation != m_lastRot)
        updateMaps(srcW, srcH, rotation);

    const size_t ySize = (size_t)m_dw * m_dh;
    const size_t size = ySize * 3 / 2;
    uint8_t *dst = static_cast<uint8_t *>(malloc(size));
    if (!dst)
        return nullptr;

    // Black in YUV limited range: Y=16, U=V=128.
    memset(dst, 16, ySize);
    memset(dst + ySize, 128, size - ySize);

    uint8_t *dstY = dst;
    uint8_t *dstC = dst + ySize;                 // NV12: interleaved UV
    uint8_t *dstU = dst + ySize;                 // I420: U then V
    uint8_t *dstV = dst + ySize + ySize / 4;

#if defined(__aarch64__)
    // Projection shm already has the encoder's dimensions. Avoid the general
    // scaler's coordinate divisions and process eight RGBA pixels at a time.
    // Keep the same BT.601 coefficients and point-sampled chroma as below.
    if (rotation == 0 && srcW == m_dw && srcH == m_dh && (m_dw % 8) == 0) {
        for (int y = 0; y < m_dh; ++y) {
            const uint8_t *row = src + (size_t)(yInverted ? srcH - 1 - y : y) * srcStride;
            for (int x = 0; x < m_dw; x += 8) {
                const uint8x8x4_t rgba = vld4_u8(row + x * 4);
                uint16x8_t luma = vmull_u8(rgba.val[0], vdup_n_u8(66));
                luma = vmlal_u8(luma, rgba.val[1], vdup_n_u8(129));
                luma = vmlal_u8(luma, rgba.val[2], vdup_n_u8(25));
                luma = vaddq_u16(luma, vdupq_n_u16(128));
                vst1_u8(dstY + (size_t)y * m_dw + x,
                         vadd_u8(vshrn_n_u16(luma, 8), vdup_n_u8(16)));
                if ((y & 1) == 0) {
                    const int16x8_t r = vreinterpretq_s16_u16(vmovl_u8(rgba.val[0]));
                    const int16x8_t g = vreinterpretq_s16_u16(vmovl_u8(rgba.val[1]));
                    const int16x8_t b = vreinterpretq_s16_u16(vmovl_u8(rgba.val[2]));
                    int16x8_t u = vmulq_n_s16(b, 112);
                    u = vmlsq_n_s16(u, r, 38); u = vmlsq_n_s16(u, g, 74);
                    int16x8_t v = vmulq_n_s16(r, 112);
                    v = vmlsq_n_s16(v, g, 94); v = vmlsq_n_s16(v, b, 18);
                    const uint8x8_t us = vadd_u8(vreinterpret_u8_s8(vshrn_n_s16(vaddq_s16(u, vdupq_n_s16(128)), 8)), vdup_n_u8(128));
                    const uint8x8_t vs = vadd_u8(vreinterpret_u8_s8(vshrn_n_s16(vaddq_s16(v, vdupq_n_s16(128)), 8)), vdup_n_u8(128));
                    const uint8x8_t ue = vuzp_u8(us, vdup_n_u8(0)).val[0];
                    const uint8x8_t ve = vuzp_u8(vs, vdup_n_u8(0)).val[0];
                    const size_t offset = (size_t)(y / 2) * (m_dw / 2) + x / 2;
                    if (m_nv12) {
                        vst1_u8(dstC + offset * 2, vzip_u8(ue, ve).val[0]);
                    } else {
                        const uint32_t up = vget_lane_u32(vreinterpret_u32_u8(ue), 0);
                        const uint32_t vp = vget_lane_u32(vreinterpret_u32_u8(ve), 0);
                        memcpy(dstU + offset, &up, 4); memcpy(dstV + offset, &vp, 4);
                    }
                }
            }
        }
        if (outSize) *outSize = size;
        return dst;
    }
#endif

    const int cw = (rotation == 90 || rotation == 270) ? srcH : srcW;
    const int ch = (rotation == 90 || rotation == 270) ? srcW : srcH;

    // Box filter: averaging the source region per output pixel. A single
    // nearest-neighbour tap turns Silica's fine dither texture into coarse
    // visible moiré on the TV; averaging cancels it. Sample counts are
    // capped to keep the cost bounded at high downscale factors.
    // Round UP: a scale factor of e.g. 1.97 (landscape) must still average
    // 2x2 — truncating to 1 silently degenerates to nearest neighbour and
    // the dither moiré returns.
    int sxN = (cw + m_boxW - 1) / (m_boxW > 0 ? m_boxW : 1);
    int syN = (ch + m_boxH - 1) / (m_boxH > 0 ? m_boxH : 1);
    if (sxN < 1) sxN = 1;
    if (sxN > 4) sxN = 4;
    if (syN < 1) syN = 1;
    if (syN > 4) syN = 4;
    const int nSamples = sxN * syN;

    for (int y = 0; y < m_boxH; y++) {
        // Position inside the rotated content raster.
        int ry = (int)((int64_t)y * ch / m_boxH);
        uint8_t *outY = dstY + (size_t)(m_boxY + y) * m_dw + m_boxX;
        const bool chromaRow = ((y & 1) == 0);
        for (int x = 0; x < m_boxW; x++) {
            int rx = (int)((int64_t)x * cw / m_boxW);
            int r = 0, g = 0, b = 0;
            for (int j = 0; j < syN; j++) {
                for (int i = 0; i < sxN; i++) {
                    int crx = rx + i;
                    int cry = ry + j;
                    if (crx >= cw) crx = cw - 1;
                    if (cry >= ch) cry = ch - 1;
                    int sx, sy;
                    switch (rotation) {
                    case 90: // content rotated CW in buffer -> rotate CCW
                        sx = cry;
                        sy = srcH - 1 - crx;
                        break;
                    case 270:
                        sx = srcW - 1 - cry;
                        sy = crx;
                        break;
                    default:
                        sx = crx;
                        sy = cry;
                        break;
                    }
                    if (yInverted)
                        sy = srcH - 1 - sy;
                    const uint8_t *p =
                        src + (size_t)sy * srcStride + (size_t)sx * 4;
                    r += p[0];
                    g += p[1];
                    b += p[2];
                }
            }
            r /= nSamples;
            g /= nSamples;
            b /= nSamples;
            outY[x] = (uint8_t)(((66 * r + 129 * g + 25 * b + 128) >> 8) + 16);
            if (chromaRow && ((x & 1) == 0)) {
                int u = ((-38 * r - 74 * g + 112 * b + 128) >> 8) + 128;
                int v = ((112 * r - 94 * g - 18 * b + 128) >> 8) + 128;
                int cy2 = (m_boxY + y) / 2;
                int cx2 = (m_boxX + x) / 2;
                if (m_nv12) {
                    uint8_t *c = dstC + (size_t)cy2 * m_dw + cx2 * 2;
                    c[0] = (uint8_t)u;
                    c[1] = (uint8_t)v;
                } else {
                    dstU[(size_t)cy2 * (m_dw / 2) + cx2] = (uint8_t)u;
                    dstV[(size_t)cy2 * (m_dw / 2) + cx2] = (uint8_t)v;
                }
            }
        }
    }

    if (outSize)
        *outSize = size;
    return dst;
}

} // namespace imira
