from __future__ import annotations
from typing import IO, Literal, NotRequired, TypedDict
import yaml
from .types import Decimalish


# Example batch file below, TypedDicts follow
# # inscription modes:
# # - `same-sat`: inscribe on the same sat
# # - `satpoints`: inscribe on the first sat of specified satpoint's output
# # - `separate-outputs`: inscribe on separate postage-sized outputs
# # - `shared-output`: inscribe on a single output separated by postage
# mode: separate-outputs
#
# # parent inscription:
# parent: 6ac5cacb768794f4fd7a78bf00f2074891fce68bd65c4ff36e77177237aacacai0
#
# # postage for each inscription:
# postage: 12345
#
# # allow reinscribing
# reinscribe: true
#
# # sat to inscribe on, can only be used with `same-sat`:
# # sat: 5000000000
#
# # rune to etch (optional)
# etching:
#   # rune name
#   rune: THE•BEST•RUNE
#   # allow subdividing super-unit into `10^divisibility` sub-units
#   divisibility: 2
#   # premine
#   premine: 1000.00
#   # total supply, must be equal to `premine + terms.cap * terms.amount`
#   supply: 10000.00
#   # currency symbol
#   symbol: $
#   # mint terms (optional)
#   terms:
#     # amount per mint
#     amount: 100.00
#     # maximum number of mints
#     cap: 90
#     # mint start and end absolute block height (optional)
#     height:
#       start: 840000
#       end: 850000
#     # mint start and end block height relative to etching height (optional)
#     offset:
#       start: 1000
#       end: 9000
#
# # inscriptions to inscribe
# inscriptions:
#   # path to inscription content
# - file: mango.avif
#   # inscription to delegate content to (optional)
#   delegate: 6ac5cacb768794f4fd7a78bf00f2074891fce68bd65c4ff36e77177237aacacai0
#   # destination (optional, if no destination is specified a new wallet change address will be used)
#   destination: bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4
#   # inscription metadata (optional)
#   metadata:
#     title: Delicious Mangos
#     description: >
#       Lorem ipsum dolor sit amet, consectetur adipiscing elit. Aliquam semper,
#       ligula ornare laoreet tincidunt, odio nisi euismod tortor, vel blandit
#       metus est et odio. Nullam venenatis, urna et molestie vestibulum, orci
#       mi efficitur risus, eu malesuada diam lorem sed velit. Nam fermentum
#       dolor et luctus euismod.
#
# - file: token.json
#   # inscription metaprotocol (optional)
#   metaprotocol: DOPEPROTOCOL-42069
#
# - file: tulip.png
#   destination: bc1pdqrcrxa8vx6gy75mfdfj84puhxffh4fq46h3gkp6jxdd0vjcsdyspfxcv6
#   metadata:
#     author: Satoshi Nakamoto


class BatchFile(TypedDict):
    mode: Literal["same-sat", "satpoints", "separate-outputs", "shared-output"]
    parent: NotRequired[str]
    postage: NotRequired[int]
    reinscribe: NotRequired[bool]
    sat: NotRequired[int]
    etching: NotRequired[BatchFileEtching]
    inscriptions: list[BatchFileInscription]


class BatchFileEtching(TypedDict):
    rune: str
    divisibility: int
    premine: Decimalish
    supply: Decimalish
    symbol: str
    terms: NotRequired[BatchFileEtchingTerms]
    turbo: bool


class BatchFileEtchingTerms(TypedDict):
    amount: Decimalish
    cap: int
    height: NotRequired[BatchFileEtchingTermsTuple]
    offset: NotRequired[BatchFileEtchingTermsTuple]


class BatchFileEtchingTermsTuple(TypedDict):
    start: int
    end: int


class BatchFileInscription(TypedDict):
    file: str
    delegate: NotRequired[str]
    destination: NotRequired[str]
    metadata: NotRequired[BatchFileInscriptionMetadata]
    metaprotocol: NotRequired[str]


class BatchFileInscriptionMetadata(TypedDict):
    title: NotRequired[str]
    description: NotRequired[str]
    author: NotRequired[str]


def create_batch_file(batch_file: BatchFile, stream: IO) -> None:
    yaml.dump(batch_file, stream)
