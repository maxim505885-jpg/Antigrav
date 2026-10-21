try:
    import matplotlib
    print("matplotlib:", matplotlib.__version__)
except Exception as e:
    print("matplotlib error:", e)

try:
    import reportlab
    print("reportlab:", reportlab.__version__)
except Exception as e:
    print("reportlab error:", e)

try:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    print("ezdxf drawing addon available!")
except Exception as e:
    print("ezdxf drawing error:", e)
