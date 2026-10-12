"""Process-local policy for Vantage's CPU image-analysis runtime."""

import os


def configure_cpu_runtime() -> None:
    """Disable OpenCV's implicit OpenCL initialization before native imports.

    Haar detection can allocate internal UMat buffers even with CPU Mat input.
    Unlike cv2.ocl.setUseOpenCL(False), this policy is shared by worker threads
    and inherited by child processes. Override enabling values deliberately;
    this is a product policy, not a machine-wide environment setting.
    """
    os.environ["OPENCV_OPENCL_RUNTIME"] = "disabled"
