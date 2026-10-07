"""System OpenSSL ChaCha20-Poly1305 for real-time screen packets."""
import ctypes as C
import ctypes.util


class NativeChaCha:
    def __init__(self,key):
        if len(key)!=32:
            raise ValueError('invalid ChaCha key')
        self.key=key
        self.lib=C.CDLL(ctypes.util.find_library('crypto'))
        signatures={
            'EVP_CIPHER_CTX_new':([],C.c_void_p),
            'EVP_CIPHER_CTX_free':([C.c_void_p],None),
            'EVP_chacha20_poly1305':([],C.c_void_p),
            'EVP_EncryptInit_ex':([C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p],C.c_int),
            'EVP_EncryptUpdate':([C.c_void_p,C.c_void_p,C.POINTER(C.c_int),C.c_void_p,C.c_int],C.c_int),
            'EVP_EncryptFinal_ex':([C.c_void_p,C.c_void_p,C.POINTER(C.c_int)],C.c_int),
            'EVP_CIPHER_CTX_ctrl':([C.c_void_p,C.c_int,C.c_int,C.c_void_p],C.c_int)}
        for name,(args,result) in signatures.items():
            fn=getattr(self.lib,name)
            fn.argtypes,fn.restype=args,result

    def seal(self,nonce,body,aad):
        if len(nonce)!=12:
            raise ValueError('invalid nonce')
        lib=self.lib
        ctx=lib.EVP_CIPHER_CTX_new()
        if not ctx:
            raise OSError('OpenSSL context allocation failed')
        def checked(value):
            if value!=1:
                raise OSError('OpenSSL screen encryption failed')
        try:
            keybuf=C.create_string_buffer(self.key)
            noncebuf=C.create_string_buffer(nonce)
            checked(lib.EVP_EncryptInit_ex(ctx,lib.EVP_chacha20_poly1305(),None,keybuf,noncebuf))
            length=C.c_int()
            aadbuf=C.create_string_buffer(aad)
            checked(lib.EVP_EncryptUpdate(ctx,None,C.byref(length),aadbuf,len(aad)))
            output=C.create_string_buffer(len(body)+16)
            source=C.create_string_buffer(body)
            checked(lib.EVP_EncryptUpdate(ctx,output,C.byref(length),source,len(body)))
            used=length.value
            checked(lib.EVP_EncryptFinal_ex(ctx,C.byref(output,used),C.byref(length)))
            used+=length.value
            tag=C.create_string_buffer(16)
            checked(lib.EVP_CIPHER_CTX_ctrl(ctx,0x10,16,tag))
            return output.raw[:used]+tag.raw
        finally:
            lib.EVP_CIPHER_CTX_free(ctx)
