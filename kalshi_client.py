"""
Kalshi API Client with request signing.
Supports both demo and production.
Public market data works without keys.
Authenticated endpoints require API key + private key.
"""

import time
import base64
import uuid
from typing import Optional, Dict, Any, List
from pathlib import Path

import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, ed25519
from cryptography.hazmat.backends import default_backend


class KalshiClient:
    def __init__(
        self,
        api_key_id: str = "",
        private_key_path: str = "",
        use_demo: bool = True,
        timeout: int = 15,
    ):
        self.api_key_id = api_key_id
        self.use_demo = use_demo
        self.timeout = timeout

        if use_demo:
            self.base_url = "https://external-api.demo.kalshi.co/trade-api/v2"
        else:
            self.base_url = "https://external-api.kalshi.com/trade-api/v2"

        self.private_key = None
        if private_key_path and Path(private_key_path).exists():
            with open(private_key_path, "rb") as f:
                key_data = f.read()
            try:
                # Try Ed25519 first (preferred by Kalshi)
                self.private_key = serialization.load_pem_private_key(
                    key_data, password=None, backend=default_backend()
                )
            except Exception:
                # Fallback for RSA
                self.private_key = serialization.load_pem_private_key(
                    key_data, password=None, backend=default_backend()
                )

    def _sign(self, method: str, path: str) -> Dict[str, str]:
        """Create authentication headers."""
        if not self.api_key_id or not self.private_key:
            return {}

        timestamp = str(int(time.time() * 1000))
        # Path must be the full path starting with /trade-api/v2... without query params
        message = f"{timestamp}{method.upper()}{path}".encode("utf-8")

        if isinstance(self.private_key, ed25519.Ed25519PrivateKey):
            signature = self.private_key.sign(message)
        else:
            # RSA-PSS
            signature = self.private_key.sign(
                message,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        auth: bool = False,
    ) -> Dict[str, Any]:
        """Make a request to the Kalshi API."""
        # endpoint should start with /
        path = f"/trade-api/v2{endpoint}"
        url = f"{self.base_url}{endpoint}"

        headers = {}
        if auth:
            headers = self._sign(method, path)

        try:
            resp = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except requests.exceptions.HTTPError as e:
            print(f"[API Error] {method} {endpoint}: {e}")
            if e.response is not None:
                try:
                    print(e.response.json())
                except Exception:
                    print(e.response.text)
            raise
        except Exception as e:
            print(f"[Request Error] {e}")
            raise

    # ---------- Public endpoints (no auth) ----------

    def get_markets(
        self,
        status: str = "open",
        series_ticker: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> Dict:
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        return self._request("GET", "/markets", params=params)

    def get_market(self, ticker: str) -> Dict:
        return self._request("GET", f"/markets/{ticker}")

    def get_orderbook(self, ticker: str, depth: int = 10) -> Dict:
        return self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})

    def get_events(self, status: str = "open", limit: int = 50) -> Dict:
        return self._request("GET", "/events", params={"status": status, "limit": limit})

    # ---------- Authenticated endpoints ----------

    def get_balance(self) -> Dict:
        return self._request("GET", "/portfolio/balance", auth=True)

    def get_positions(self) -> Dict:
        return self._request("GET", "/portfolio/positions", auth=True)

    def create_order(
        self,
        ticker: str,
        side: str,          # "bid" (buy yes) or "ask" (sell yes)
        count: str,         # e.g. "5.00"
        price: str,         # e.g. "0.4500" (dollars)
        client_order_id: Optional[str] = None,
        time_in_force: str = "good_till_canceled",
        post_only: bool = True,
    ) -> Dict:
        """
        Place a limit order (V2 style).
        side: "bid" = buy YES, "ask" = sell YES
        """
        if client_order_id is None:
            client_order_id = str(uuid.uuid4())

        order = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "side": side,
            "count": count,
            "price": price,
            "time_in_force": time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
            "post_only": post_only,
        }
        return self._request("POST", "/portfolio/events/orders", json_data=order, auth=True)

    def cancel_order(self, order_id: str) -> Dict:
        return self._request("DELETE", f"/portfolio/orders/{order_id}", auth=True)

    def get_orders(self, status: str = "resting") -> Dict:
        return self._request("GET", "/portfolio/orders", params={"status": status}, auth=True)

    def cancel_all_orders(self) -> None:
        """Best-effort cancel of all resting orders."""
        try:
            orders = self.get_orders(status="resting")
            for order in orders.get("orders", []):
                try:
                    self.cancel_order(order["order_id"])
                    print(f"Cancelled order {order['order_id']}")
                except Exception as e:
                    print(f"Failed to cancel {order.get('order_id')}: {e}")
        except Exception as e:
            print(f"Error fetching orders to cancel: {e}")