from typing import Any, Callable, NewType, Self, Literal, TypeGuard, get_args
from dataclasses import dataclass
import re
import asyncio
import json
import time

import httpx

Product = NewType("Product", str)

products: list[Product] = [
  Product("wow"),
  Product("wow_classic"),
  Product("wow_classic_era"),
  Product("wow_anniversary"),
]


def get_version_endpoint(product: Product) -> str:
  return f"http://us.patch.battle.net:1119/{product}/versions"


HeaderType = Literal["STRING", "HEX", "DEC"]


def is_header_type(value: str) -> TypeGuard[HeaderType]:
  return value in get_args(HeaderType)


type DataParser = Callable[[str, Header], Any]

data_parsers: dict[HeaderType, DataParser] = {
  "HEX": lambda s, h: parse_hex(s, h),
  "STRING": lambda s, h: parse_string(s, h),
  "DEC": lambda s, h: parse_dec(s, h),
}


@dataclass
class Header:
  name: str
  type_: HeaderType
  size_bytes: int

  @classmethod
  def parse(cls, raw: str) -> Self:
    name, rest = raw.split("!")
    type_, size_bytes = rest.split(":")
    type_ = type_.upper()
    if not is_header_type(type_):
      raise ValueError(f"Invalid header type: {type_}")
    return cls(name=name, type_=type_, size_bytes=int(size_bytes))

  def _get_data_parser(self) -> DataParser:
    return data_parsers[self.type_]

  def parse_data(self, raw: str) -> Any:
    parser = self._get_data_parser()
    return parser(raw, self)


def parse_hex(s: str, header: Header) -> bytes | None:
  if s == "":
    return
  value = bytes.fromhex(s)
  if len(value) != header.size_bytes:
    raise ValueError(f"Expected {header.size_bytes} bytes, got {len(value)}")
  return value


def parse_string(s: str, header: Header) -> str:
  # size is ignored, is always expressed as 0, no check needed
  return s


def parse_dec(s: str, header: Header) -> int | None:
  if s == "":
    return
  value = int(s)
  if value.bit_length() > header.size_bytes * 8:
    raise ValueError(f"Expected {header.size_bytes * 8} bits, got {value.bit_length()}")
  return value


seqn_pattern = re.compile(r"^## seqn = (\d+)$")


@dataclass
class RibbitResponse:
  """
  A [WoW Ribbit](https://wowdev.wiki/Ribbit) response. Or it might be
  [TACT](https://wowdev.wiki/TACT). I dunno, the name is not well-documented.
  """

  sequence_number: int
  _headers: list[Header]
  _rows: list[list[str]]

  @classmethod
  def parse(cls, raw: str) -> Self:
    header_row, seqn_row, *data_rows = raw.splitlines()
    headers = [Header.parse(h) for h in header_row.split("|")]

    seqn_match = seqn_pattern.match(seqn_row)
    if not seqn_match:
      raise ValueError(f"Invalid sequence number row: {seqn_row}")
    sequence_number = int(seqn_match.group(1))

    rows: list[list[str]] = []
    for row in data_rows:
      values = row.split("|")
      if len(values) != len(headers):
        raise ValueError(f"Invalid data row: {row}")
      rows.append(values)

    return cls(sequence_number=sequence_number, _headers=headers, _rows=rows)

  def get(self, row: int, column: str) -> Any:
    header_indices = {h.name: i for i, h in enumerate(self._headers)}
    if column not in header_indices:
      raise ValueError(f"Invalid column name: {column}")
    col_index = header_indices[column]
    header = self._headers[col_index]
    raw_value = self._rows[row][col_index]
    return header.parse_data(raw_value)

  def get_columns(self) -> list[str]:
    return [h.name for h in self._headers]

  def get_all(self) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row_index in range(len(self._rows)):
      row_dict: dict[str, Any] = {}
      for header in self._headers:
        row_dict[header.name] = self.get(row_index, header.name)
      result.append(row_dict)
    return result


async def get_versions(product: Product) -> RibbitResponse:
  url = get_version_endpoint(product)
  async with httpx.AsyncClient() as client:
    response = await client.get(url)
    response.raise_for_status()
    return RibbitResponse.parse(response.text)


@dataclass
class BuildVersion:
  major: str
  minor: str
  patch: str
  build: str

  @classmethod
  def parse(cls, s: str) -> Self:
    parts = s.split(".")
    if len(parts) != 4:
      raise ValueError(f"Invalid build version: {s}")
    major, minor, patch, build = parts
    return cls(major=major, minor=minor, patch=patch, build=build)

  @property
  def version(self) -> str:
    return f"{self.major}.{self.minor}.{self.patch}"

  @property
  def interface_version(self) -> str:
    """
    Produce an interface version like `10203`.
    """
    # the logic is major + zero-padded two-digit minor + zero-padded two-digit patch
    return f"{self.major}{int(self.minor):02d}{int(self.patch):02d}"


async def run():
  tasks = [get_versions(product) for product in products]
  responses = await asyncio.gather(*tasks)

  root: dict[str, Any] = {}
  root["retrieval_datetime"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
  root["products"] = {}

  for product, response in zip(products, responses):
    product_dict: dict[str, Any] = {}
    product_dict["name"] = product
    product_dict["sequence_number"] = response.sequence_number
    product_dict["versions"] = []
    versions: list[dict[str, Any]] = product_dict["versions"]

    for row in response.get_all():
      version_str = row["VersionsName"]
      build_version = BuildVersion.parse(version_str)
      version_entry: dict[str, Any] = {
        "region": row["Region"],
        "version": build_version.version,
        "build": build_version.build,
        "interface": build_version.interface_version,
      }
      versions.append(version_entry)

    root["products"][product] = product_dict
  print(json.dumps(root, indent=2))


def main():
  asyncio.run(run())


if __name__ == "__main__":
  main()
