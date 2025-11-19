"""Position models for sj_sync."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Union, TypedDict
from shioaji.constant import Action, StockOrderCond


class AccountDict(TypedDict):
    """Account dictionary structure from deal callback."""

    broker_id: str
    account_id: str


class StockPosition(BaseModel):
    """Stock position model for external API.

    Public-facing position model with essential fields:
    - code: Stock symbol
    - direction: Buy or Sell (Action enum)
    - quantity: Current position quantity (in shares or lots depending on unit)
    - yd_quantity: Yesterday's position quantity (fixed reference, never modified)
    - cond: Order condition (StockOrderCond enum)
    """

    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    code: str = Field(..., description="Stock code/symbol")
    direction: Action = Field(..., description="Buy or Sell")
    quantity: int = Field(default=0, description="Current position quantity")
    yd_quantity: int = Field(
        default=0, description="Yesterday's position quantity (fixed)"
    )
    cond: StockOrderCond = Field(
        default=StockOrderCond.Cash, description="Order condition"
    )


class StockPositionInner(StockPosition):
    """Internal stock position model with calculation fields.

    Extends StockPosition with internal tracking fields:
    - yd_offset_quantity: Yesterday's offset quantity (accumulated today)

    This is used internally for position calculations and is never exposed to users.

    Calculations:
    - Yesterday's actual remaining = yd_quantity - yd_offset_quantity
    - Today's actual remaining = quantity - (yd_quantity - yd_offset_quantity)
    """

    yd_offset_quantity: int = Field(
        default=0, description="Yesterday's offset quantity (today)"
    )


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
