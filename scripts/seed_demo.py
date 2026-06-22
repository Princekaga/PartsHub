"""Load a small, realistic demo dataset so you can try the UI without scraping.

Includes the same part (e.g. "Arduino Uno R3") listed by several vendors so the
price-comparison feature has something to show.

Usage:  python -m scripts.seed_demo
"""
from app.database import init_db
from app.scrapers.base import normalized_product
from app.scrapers.runner import _upsert

DEMO = [
    # --- Arduino Uno R3 across three vendors (for comparison) ---
    dict(vendor="robocraze", vendor_label="Robocraze", external_id="demo-uno-1",
         title="Arduino Uno R3 Development Board (with USB Cable)", brand="Arduino",
         category="Development Boards", price=499.0, compare_at_price=699.0,
         in_stock=True, url="https://robocraze.com/products/arduino-uno-r3",
         image="https://cdn.shopify.com/s/files/1/0559/1970/6265/files/arduino-uno.png"),
    dict(vendor="thinkrobotics", vendor_label="ThinkRobotics", external_id="demo-uno-2",
         title="Arduino Uno R3 Board with USB Cable", brand="Arduino",
         category="Microcontroller Boards", price=549.0, compare_at_price=None,
         in_stock=True, url="https://thinkrobotics.com/products/arduino-uno-r3",
         image=""),
    dict(vendor="quartzcomponents", vendor_label="QuartzComponents", external_id="demo-uno-3",
         title="Arduino Uno R3 Development Board", brand="Arduino",
         category="Boards", price=470.0, compare_at_price=620.0,
         in_stock=False, url="https://quartzcomponents.com/products/arduino-uno-r3",
         image=""),

    # --- ESP32 across two vendors ---
    dict(vendor="robocraze", vendor_label="Robocraze", external_id="demo-esp32-1",
         title="ESP32 WROOM-32 Development Board WiFi + Bluetooth", brand="Espressif",
         category="WiFi Boards", price=389.0, compare_at_price=499.0,
         in_stock=True, url="https://robocraze.com/products/esp32-wroom-32", image=""),
    dict(vendor="quartzcomponents", vendor_label="QuartzComponents", external_id="demo-esp32-2",
         title="ESP32 WROOM 32 WiFi Bluetooth Development Board", brand="Espressif",
         category="IoT", price=410.0, compare_at_price=None,
         in_stock=True, url="https://quartzcomponents.com/products/esp32-wroom-32", image=""),

    # --- Misc singles ---
    dict(vendor="thinkrobotics", vendor_label="ThinkRobotics", external_id="demo-l298n",
         title="L298N Motor Driver Module Dual H-Bridge", brand="Generic",
         category="Motor Drivers", price=85.0, compare_at_price=120.0,
         in_stock=True, url="https://thinkrobotics.com/products/l298n", image=""),
    dict(vendor="robocraze", vendor_label="Robocraze", external_id="demo-nema17",
         title="NEMA 17 Stepper Motor 1.8 deg 4-wire", brand="Generic",
         category="Motors", price=649.0, compare_at_price=None,
         in_stock=True, url="https://robocraze.com/products/nema-17", image=""),
    dict(vendor="quartzcomponents", vendor_label="QuartzComponents", external_id="demo-hcsr04",
         title="HC-SR04 Ultrasonic Distance Sensor Module", brand="Generic",
         category="Sensors", price=65.0, compare_at_price=99.0,
         in_stock=True, url="https://quartzcomponents.com/products/hc-sr04", image=""),
]


def main():
    init_db()
    # Give each demo product a fake cart_ref (variant id) so the deep-link checkout
    # shows real pre-filled cart links in the demo (all demo vendors are Shopify-type).
    records = [
        normalized_product(**d, sku="", description="", currency="INR", cart_ref=str(40000 + i))
        for i, d in enumerate(DEMO)
    ]
    n = _upsert(records)
    print(f"Seeded {n} demo products. Run: uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
