"""Abstract base scraper — Amazon and Flipkart subclass this."""
from abc import ABC, abstractmethod
from  models.product import Product
from  models.offer import Offer


class BaseScraper(ABC):

    @abstractmethod
    async def search_products(
        self,
        query: str,
        price_min: float,
        price_max: float,
        max_results: int,
    ) -> list[Product]:
        """Scrape search result page and return product listings."""
        ...

    @abstractmethod
    async def scrape_offers(self, product: Product) -> list[Offer]:
        """Scrape product detail page and return raw offer objects."""
        ...
