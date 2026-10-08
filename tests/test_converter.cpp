#include "convert.h"
#include <vector>
#include <cstring>
#include <cstdlib>
#include <cstdio>

// Compare the projection fast path with the general scalar implementation.
// Rotation 360 follows the general path's identity/default branch.
int main()
{
    for (int width : {8, 16, 1280, 1920}) {
        const int height = 32, stride = width * 4 + 16;
        std::vector<unsigned char> rgba(stride * height);
        unsigned seed = 17;
        for (auto &pixel : rgba) {
            seed = seed * 1664525u + 1013904223u;
            pixel = seed >> 24;
        }
        for (bool inverted : {false, true}) for (bool nv12 : {false, true}) {
            imira::FrameConverter fast, reference;
            fast.configure(width, height, nv12);
            reference.configure(width, height, nv12);
            size_t aSize = 0, bSize = 0;
            auto *a = fast.convert(rgba.data(), width, height, stride, inverted, 0, &aSize);
            auto *b = reference.convert(rgba.data(), width, height, stride, inverted, 360, &bSize);
            if (!a || !b || aSize != bSize || std::memcmp(a, b, aSize)) {
                std::fprintf(stderr, "conversion mismatch: width=%d inverted=%d nv12=%d\n", width, inverted, nv12);
                return 1;
            }
            std::free(a); std::free(b);
        }
    }
    std::puts("NEON conversion matches scalar output (16 cases)");
}
