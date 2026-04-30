"""Position models for sj_sync."""

from pydantic import BaseModel, ConfigDict, Field, computed_field
from typing import Union, TypedDict
from shioaji.constant import Action, StockOrderCond


class AccountDict(TypedDict):
    """Account dictionary structure from deal callback."""

    broker_id: str
    account_id: str


class StockPosition(BaseModel):
    """Stock position model for external API.

    Public-facing position model:
    - code: Stock symbol
    - direction: Buy or Sell (Action enum)
    - quantity: Current position quantity (in shares or lots depending on unit)
    - yd_quantity: Yesterday's position quantity (fixed reference, never modified)
    - yd_offset_quantity: Amount of yd_quantity already offset by today's
      opposite-direction trades (accumulates intraday)
    - yd_remaining_quantity: Computed; yd_quantity - yd_offset_quantity
    - cond: Order condition (StockOrderCond enum)
    """

    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    code: str = Field(..., description="Stock code/symbol")
    direction: Action = Field(..., description="Buy or Sell")
    quantity: int = Field(default=0, description="Current position quantity")
    yd_quantity: int = Field(
        default=0, description="Yesterday's position quantity (fixed)"
    )
    yd_offset_quantity: int = Field(
        default=0,
        description="Amount of yd_quantity offset by today's opposite-direction trades",
    )
    cond: StockOrderCond = Field(
        default=StockOrderCond.Cash, description="Order condition"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def yd_remaining_quantity(self) -> int:
        """Yesterday's remaining quantity = yd_quantity - yd_offset_quantity."""
        return self.yd_quantity - self.yd_offset_quantity


class FuturesPosition(BaseModel):
    """Futures/Options position model.

    Simplified futures position tracking:
    - code: Contract code
    - direction: Buy or Sell (Action enum)
    - quantity: Current position quantity
    # - yd_quantity: Yesterday's position quantity
    """

    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    code: str = Field(..., description="Contract code")
    direction: Action = Field(..., description="Buy or Sell")
    quantity: int = Field(default=0, description="Current position quantity")
    # yd_quantity: int = Field(default=0, description="Yesterday's position quantity")


# Type alias for any position type
Position = Union[StockPosition, FuturesPosition]
