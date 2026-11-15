class OcrFailed(RuntimeError):
    """OCR could not run, which is not the same as "this frame has no text".

    An empty result means the frame was read and nothing was found; this exception
    means the read never happened (missing package/model, decode error, engine
    crash). Callers must keep those apart: reporting a failed read as empty is
    how a broken OCR install turned into a confident "no text here".
    """
