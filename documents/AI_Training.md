# AI Training Documentation

## Training Data Source:

https://universe.roboflow.com/hcmut-yxyhm/3d-printing-defects

## Training Python Script:

train_script.py - 
```bash
from ultralytics import YOLO

def main():
    model = YOLO("yolov8n.pt")

    model.train(
        data="data.yaml",
        epochs=150,
        imgsz=640,
        batch=24,
        workers=8,
        device=0,

        # small-object optimized
        mosaic=0.5,
        mixup=0.1,
        hsv_h=0.02,
        hsv_s=0.8,
        hsv_v=0.5,
        fliplr=0.5,
        copy_paste=0.1,
        translate=0.10,
        scale=0.40,
        shear=0.1,
        perspective=0.0,
        erasing=0.5,
        auto_augment="randaugment",

        close_mosaic=5,
        multi_scale=False,        # disabled for speed

        optimizer="AdamW",
        lr0=0.001,
        lrf=0.01,
        momentum=0.9,
        weight_decay=0.0005,
        warmup_epochs=5,
        patience=80,

        project="runs",
        name="defects_nano_fast",
        exist_ok=True
    )

    print("\nTraining finished: runs/detect/defects_nano_fast/weights/best.pt")


if __name__ == "__main__":
    main()
```

## File Conversion Source:

.pt to .tflite conversion - 

https://colab.research.google.com/drive/13YXnw2LqIHvQoQ9EvpWYOEkAi27ddriC?usp=sharing#scrollTo=LEE4ngaxBsJk

## Results:

<img width="2400" height="1200" alt="results" src="https://github.com/user-attachments/assets/03560fdd-8508-4a30-9c93-6596083c57d2" />


**mAP@50 Values**:

- All classes: 0.552
- Spaghetti: 0.925
- Stringing: 0.298
- Zits: 0.431
