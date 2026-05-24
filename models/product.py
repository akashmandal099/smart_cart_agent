from __future__ import annotations
from pydantic import BaseModel
from enum import Enum
from typing import Optional
from datetime import datetime


class Platform(str, Enum):
    AMAZON   = "amazon"
    FLIPKART = "flipkart"


class Product(BaseModel):
    platform: Platform
    product_id: str
    title: str
    brand: Optional[str] = None
    base_price: float
    mrp: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    image_url: Optional[str] = None
    product_url: str
    in_stock: bool = True
    badges: list[str] = []
    scraped_at: datetime = datetime.utcnow()

    @property
    def discount_pct(self) -> Optional[float]:
        if self.mrp and self.mrp > self.base_price:
            return round((self.mrp - self.base_price) / self.mrp * 100, 1)
        return None
