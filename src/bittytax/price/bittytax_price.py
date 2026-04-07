# -*- coding: utf-8 -*-
# (c) Nano Nano Ltd 2019

import argparse
import platform
import re
import sys
from decimal import Decimal, InvalidOperation
from typing import List

import colorama
import dateutil.parser
from colorama import Fore

from ..bt_types import AssetSymbol, Timestamp
from ..config import config
from ..constants import ERROR, TZ_UTC, WARNING
from ..utils import is_compiled
from ..version import __version__
from .assetdata import AsPriceRecord, AsRecord, AssetData
from .datasource import DataSourceBase
from .exceptions import DataSourceError
from .valueasset import ValueAsset

CMD_LATEST = "latest"
CMD_HISTORY = "historic"
CMD_LIST = "list"
CMD_CACHE = "cache"

if sys.stdout.encoding != "UTF-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def main() -> None:
    colorama.init()
    parser = argparse.ArgumentParser()

    if is_compiled():
        version_str = f"{parser.prog} v{__version__} (compiled)"
    else:
        version_str = f"{parser.prog} v{__version__}"

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=version_str,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_latest = subparsers.add_parser(
        CMD_LATEST,
        help="get the latest price of an asset",
        description=f"Get the latest [asset] price (in {config.ccy}). "
        "If no data source [-ds] is given, the same data source(s) as 'bittytax' are used.",
    )
    parser_latest.add_argument(
        "asset",
        type=str,
        nargs=1,
        help="symbol of cryptoasset or fiat currency (i.e. BTC/LTC/ETH or EUR/USD)",
    )
    parser_latest.add_argument(
        "quantity",
        type=validate_quantity,
        nargs="?",
        help="quantity to price (optional)",
    )
    parser_latest.add_argument(
        "-ds",
        choices=datasource_choices(upper=True) + ["ALL"],
        metavar="{" + ", ".join(datasource_choices()) + "} or ALL",
        dest="datasource",
        type=str.upper,
        help="specify the data source to use, or all",
    )
    parser_latest.add_argument(
        "--offline", action="store_true", help="use only cached price data"
    )
    parser_latest.add_argument(
        "--max-price-age",
        type=int,
        default=30,
        dest="max_price_age",
        metavar="DAYS",
        help="accept cached 'latest' prices up to DAYS old (default: 30, used with --offline)",
    )
    parser_latest.add_argument("-d", "--debug", action="store_true", help="enable debug logging")

    parser_history = subparsers.add_parser(
        CMD_HISTORY,
        help="get the historical price of an asset",
        description=f"Get the historic [asset] price (in {config.ccy}) for the [date] specified. "
        "If no data source [-ds] is given, the same data source(s) as 'bittytax' are used.",
    )
    parser_history.add_argument(
        "asset",
        type=str.upper,
        nargs=1,
        help="symbol of cryptoasset or fiat currency (i.e. BTC/LTC/ETH or EUR/USD)",
    )
    parser_history.add_argument(
        "date", type=validate_date, nargs=1, help="date (YYYY-MM-DD or DD/MM/YYYY)"
    )
    parser_history.add_argument(
        "quantity",
        type=validate_quantity,
        nargs="?",
        help="quantity to price (optional)",
    )
    parser_history.add_argument(
        "-ds",
        choices=datasource_choices(upper=True) + ["ALL"],
        metavar="{" + ", ".join(datasource_choices()) + "} or ALL",
        dest="datasource",
        type=str.upper,
        help="specify the data source to use, or all",
    )
    parser_history.add_argument(
        "-nc",
        "--nocache",
        dest="no_cache",
        action="store_true",
        help="bypass data cache",
    )
    parser_history.add_argument(
        "--offline", action="store_true", help="use only cached price data"
    )
    parser_history.add_argument("-d", "--debug", action="store_true", help="enable debug logging")

    parser_list = subparsers.add_parser(
        CMD_LIST,
        help="list all assets",
        description="List all assets, or filter by [asset].",
    )
    parser_list.add_argument(
        "asset",
        type=str,
        nargs="?",
        help="symbol of cryptoasset or fiat currency (i.e. BTC/LTC/ETH or EUR/USD)",
    )
    parser_list.add_argument(
        "-s",
        type=str,
        nargs="+",
        metavar="SEARCH_TERM",
        dest="search_terms",
        help="search assets using SEARCH_TERM(S)",
    )
    parser_list.add_argument(
        "-ds",
        choices=datasource_choices(upper=True) + ["ALL"],
        metavar="{" + ", ".join(datasource_choices()) + "} or ALL",
        dest="datasource",
        type=str.upper,
        help="specify the data source to use, or all",
    )
    parser_list.add_argument("-d", "--debug", action="store_true", help="enable debug logging")

    parser_cache = subparsers.add_parser(
        CMD_CACHE,
        help="manage the price cache",
        description="Inspect, export or import the local price cache.",
    )
    cache_subparsers = parser_cache.add_subparsers(dest="cache_command", required=True)

    parser_cache_info = cache_subparsers.add_parser(
        "info",
        help="show cache contents",
        description="Display a summary of all cached price data.",
    )
    parser_cache_info.add_argument(
        "-ds",
        choices=datasource_choices(upper=True),
        metavar="{" + ", ".join(datasource_choices()) + "}",
        dest="datasource",
        type=str.upper,
        help="only show cache for this data source",
    )

    parser_cache_export = cache_subparsers.add_parser(
        "export",
        help="export cached price data to a file",
        description="Export cached price data to a portable JSON file.",
    )
    parser_cache_export.add_argument(
        "output_file", type=str, help="output filename (JSON)"
    )
    parser_cache_export.add_argument(
        "-ds",
        choices=datasource_choices(upper=True),
        metavar="{" + ", ".join(datasource_choices()) + "}",
        dest="datasource",
        type=str.upper,
        help="only export cache for this data source",
    )
    parser_cache_export.add_argument(
        "--asset",
        type=str.upper,
        metavar="SYMBOL",
        help="only export entries for this asset symbol",
    )
    parser_cache_export.add_argument(
        "--from",
        type=validate_date,
        dest="date_from",
        metavar="DATE",
        help="only export entries from this date (YYYY-MM-DD)",
    )
    parser_cache_export.add_argument(
        "--to",
        type=validate_date,
        dest="date_to",
        metavar="DATE",
        help="only export entries up to this date (YYYY-MM-DD)",
    )

    parser_cache_import = cache_subparsers.add_parser(
        "import",
        help="import cached price data from a file",
        description="Import price data from a portable JSON file into the local cache.",
    )
    parser_cache_import.add_argument(
        "input_file", type=str, help="input filename (JSON)"
    )
    parser_cache_import.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite existing cache entries (default: skip duplicates)",
    )

    args = parser.parse_args()
    config.debug = args.debug
    config.offline = getattr(args, "offline", False)
    config.max_price_age = getattr(args, "max_price_age", 30)

    if config.debug:
        print(f"{Fore.YELLOW}{version_str}")
        print(f"{Fore.GREEN}python: v{platform.python_version()}")
        print(f"{Fore.GREEN}system: {platform.system()}, release: {platform.release()}")
        for arg in vars(args):
            print(f"{Fore.GREEN}args: {arg}: {getattr(args, arg)}")
        config.output_config(sys.stdout)

    if args.command in (CMD_LATEST, CMD_HISTORY):
        symbol = args.asset[0]
        asset = price = False

        try:
            if args.datasource:
                if args.command == CMD_HISTORY:
                    assets = AssetData().get_historic_price_ds(
                        symbol, args.date[0], args.datasource, args.no_cache
                    )
                else:
                    assets = AssetData().get_latest_price_ds(symbol, args.datasource)
                btc = None
                for asset_data in assets:
                    if asset_data["price"] is None:
                        continue

                    output_ds_price(asset_data)
                    price_ccy = None
                    if asset_data["quote"] == "BTC":
                        if btc is None:
                            if args.command == CMD_HISTORY:
                                btc = get_historic_btc_price(args.date[0])
                            else:
                                btc = get_latest_btc_price()

                        if btc["price"] is not None:
                            price_ccy = btc["price"] * asset_data["price"]
                            output_ds_price(btc)
                    else:
                        price_ccy = asset_data["price"]

                    if price_ccy is not None:
                        output_price(symbol, price_ccy, args.quantity)
                        price = True

                if assets:
                    asset = True
            else:
                value_asset = ValueAsset(price_tool=True)
                if args.command == CMD_HISTORY:
                    price_ccy2, name, _ = value_asset.get_historical_price(
                        symbol, args.date[0], args.no_cache
                    )
                else:
                    price_ccy2, name, _ = value_asset.get_latest_price(symbol)

                if price_ccy2 is not None:
                    output_price(symbol, price_ccy2, args.quantity)
                    price = True

                if name:
                    asset = True

        except DataSourceError as e:
            parser.exit(message=f"{ERROR} {e}\n")

        if not asset:
            if config.offline:
                parser.exit(
                    message=f"{WARNING} No cached data found for {symbol}.\n"
                    f"  Populate the cache online:\n"
                    f"    bittytax_price historic {symbol} <date>\n"
                    f"  Or import a cache file from another machine:\n"
                    f"    bittytax_price cache import <file>\n"
                )
            parser.exit(message=f"{WARNING} Prices for {symbol} are not supported\n")

        if not price:
            if config.offline:
                if args.command == CMD_HISTORY:
                    date_str = f"{args.date[0]:%Y-%m-%d}"
                    parser.exit(
                        message=f"{WARNING} No cached price for {symbol} on {date_str}.\n"
                        f"  Populate the cache online:\n"
                        f"    bittytax_price historic {symbol} {date_str}\n"
                        f"  Or import a cache file from another machine:\n"
                        f"    bittytax_price cache import <file>\n"
                    )
                else:
                    parser.exit(
                        message=f"{WARNING} No cached 'latest' price for {symbol} "
                        f"within {config.max_price_age} day(s).\n"
                        f"  Populate the cache online:\n"
                        f"    bittytax_price latest {symbol}\n"
                        f"  Or increase the accepted age:\n"
                        f"    bittytax_price latest {symbol} --offline --max-price-age <days>\n"
                        f"  Or import a cache file from another machine:\n"
                        f"    bittytax_price cache import <file>\n"
                    )
            if args.command == CMD_HISTORY:
                parser.exit(
                    message=f"{WARNING} Price for {symbol} on {args.date[0]:%Y-%m-%d} "
                    "is not available\n"
                )
            else:
                parser.exit(message=f"{WARNING} Current price for {symbol} is not available\n")
    elif args.command == CMD_LIST:
        symbol = args.asset
        try:
            asset_list = AssetData().get_assets(symbol, args.datasource, args.search_terms)
        except DataSourceError as e:
            parser.exit(message=f"{ERROR} {e}\n")

        if symbol and not asset_list:
            parser.exit(message=f"{WARNING} Asset {symbol} not found\n")

        if args.search_terms and not asset_list:
            parser.exit(message="No results found\n")

        output_assets(asset_list)
    elif args.command == CMD_CACHE:
        if args.cache_command == "info":
            do_cache_info(args.datasource if hasattr(args, "datasource") else None)
        elif args.cache_command == "export":
            do_cache_export(
                args.output_file,
                getattr(args, "datasource", None),
                getattr(args, "asset", None),
                getattr(args, "date_from", None),
                getattr(args, "date_to", None),
            )
        elif args.cache_command == "import":
            do_cache_import(args.input_file, args.overwrite)


def do_cache_info(datasource_filter: str) -> None:
    import os as _os

    from ..constants import CACHE_DIR as _CACHE_DIR

    config.offline = True
    print(f"{Fore.WHITE}Cache directory: {_CACHE_DIR}\n")

    for ds_class in DataSourceBase.__subclasses__():
        if datasource_filter and ds_class.__name__.upper() != datasource_filter.upper():
            continue
        try:
            ds = ds_class()
        except Exception:  # pylint: disable=broad-except
            continue

        cache_file = _os.path.join(_CACHE_DIR, ds.name() + ".json")
        if not _os.path.exists(cache_file):
            continue

        file_size = _os.path.getsize(cache_file)
        total_entries = sum(len(dates) for dates in ds.prices.values())
        print(f"{Fore.CYAN}{ds.name()}.json  ({file_size:,} bytes)")
        print(f"  Pairs: {len(ds.prices)}, Total entries: {total_entries:,}")

        for pair in sorted(ds.prices):
            if not ds.prices[pair]:
                continue
            dates = sorted(ds.prices[pair].keys())
            print(
                f"  {Fore.WHITE}{pair}  "
                f"{dates[0]} \u2192 {dates[-1]}  "
                f"({len(dates):,} entries)"
            )

        if ds.latest_cache:
            print(f"  {Fore.YELLOW}Latest cache:")
            now = _os.path.getmtime(cache_file)
            for pair, entry in sorted(ds.latest_cache.items()):
                from datetime import datetime as _dt

                fetched = _dt.fromisoformat(entry["fetched_at"])
                age_days = (_dt.utcnow() - fetched).days
                age_str = f"{age_days} day{'s' if age_days != 1 else ''} ago"
                print(
                    f"    {Fore.WHITE}{pair}  fetched: {fetched:%Y-%m-%d %H:%M}  ({age_str})"
                )
        print()


def do_cache_export(
    output_file: str,
    datasource_filter: str,
    asset_filter: str,
    date_from,
    date_to,
) -> None:
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    config.offline = True

    export_data = {
        "version": 1,
        "exported_at": _dt.now(_tz.utc).isoformat(),
        "datasources": {},
        "latest": {},
    }

    for ds_class in DataSourceBase.__subclasses__():
        if datasource_filter and ds_class.__name__.upper() != datasource_filter.upper():
            continue
        try:
            ds = ds_class()
        except Exception:  # pylint: disable=broad-except
            continue

        ds_name = ds.name()
        historical: dict = {}
        for pair, dates in ds.prices.items():
            if asset_filter and not pair.startswith(asset_filter.upper() + "/"):
                continue
            filtered = {
                f"{date:%Y-%m-%d}": {
                    "price": ds.decimal_to_str(entry["price"]),
                    "url": entry["url"],
                }
                for date, entry in dates.items()
                if (date_from is None or date >= date_from.date())
                and (date_to is None or date <= date_to.date())
            }
            if filtered:
                historical[pair] = filtered

        if historical:
            export_data["datasources"][ds_name] = historical

        latest: dict = {}
        for pair, entry in ds.latest_cache.items():
            if asset_filter and not pair.startswith(asset_filter.upper() + "/"):
                continue
            latest[pair] = {
                "price": ds.decimal_to_str(entry["price"]),
                "url": entry["url"],
                "fetched_at": entry["fetched_at"],
            }
        if latest:
            export_data["latest"][ds_name] = latest

    total_hist = sum(
        sum(len(dates) for dates in ds_data.values())
        for ds_data in export_data["datasources"].values()
    )
    total_latest = sum(len(lv) for lv in export_data["latest"].values())

    with open(output_file, "w", encoding="utf-8") as f:
        _json.dump(export_data, f, indent=4, sort_keys=True)

    print(
        f"{Fore.WHITE}Exported {total_hist:,} historical and {total_latest} latest "
        f"cache entries to {output_file}"
    )


def do_cache_import(input_file: str, overwrite: bool) -> None:
    import json as _json
    from decimal import Decimal as _Decimal

    from ..bt_types import Date as _Date, SourceUrl as _SourceUrl, TradingPair as _TP
    from .datasource import DsLatestCacheEntry as _LatestEntry

    config.offline = True

    with open(input_file, "r", encoding="utf-8") as f:
        import_data = _json.load(f)

    if import_data.get("version") != 1:
        print(f"{ERROR} Unsupported cache export version: {import_data.get('version')}")
        return

    ds_map = {ds_class.__name__: ds_class for ds_class in DataSourceBase.__subclasses__()}

    added = 0
    skipped = 0

    for ds_name, pair_data in import_data.get("datasources", {}).items():
        if ds_name not in ds_map:
            print(f"{WARNING} Unknown data source '{ds_name}', skipping")
            continue
        try:
            ds = ds_map[ds_name]()
        except Exception:  # pylint: disable=broad-except
            print(f"{WARNING} Could not load data source '{ds_name}', skipping")
            continue

        for pair_str, date_data in pair_data.items():
            pair = _TP(pair_str)
            if pair not in ds.prices:
                ds.prices[pair] = {}
            for date_str, entry in date_data.items():
                date = DataSourceBase.str_to_date(date_str)
                if date in ds.prices[pair] and not overwrite:
                    skipped += 1
                    continue
                ds.prices[pair][date] = {
                    "price": DataSourceBase.str_to_decimal(entry["price"]),
                    "url": _SourceUrl(entry["url"]),
                }
                added += 1

        for pair_str, entry in import_data.get("latest", {}).get(ds_name, {}).items():
            pair = _TP(pair_str)
            if pair in ds.latest_cache and not overwrite:
                skipped += 1
                continue
            ds.latest_cache[pair] = _LatestEntry(
                price=DataSourceBase.str_to_decimal(entry["price"]),
                url=_SourceUrl(entry["url"]),
                fetched_at=entry["fetched_at"],
            )
            added += 1

        ds._cache_prices()  # pylint: disable=protected-access

    print(f"{Fore.WHITE}Import complete: {added:,} entries added, {skipped:,} skipped")


def get_latest_btc_price() -> AsPriceRecord:
    price_ccy, name, data_source = ValueAsset().get_latest_price(AssetSymbol("BTC"))
    if price_ccy is not None:
        return AsPriceRecord(
            symbol=AssetSymbol("BTC"),
            name=name,
            data_source=data_source,
            price=price_ccy,
            quote=config.ccy,
        )
    raise RuntimeError("BTC price is not available")


def get_historic_btc_price(date: Timestamp) -> AsPriceRecord:
    price_ccy, name, data_source = ValueAsset().get_historical_price(AssetSymbol("BTC"), date)
    if price_ccy is not None:
        return AsPriceRecord(
            symbol=AssetSymbol("BTC"),
            name=name,
            data_source=data_source,
            price=price_ccy,
            quote=config.ccy,
        )
    raise RuntimeError("BTC price is not available")


def output_price(symbol: AssetSymbol, price_ccy: Decimal, quantity: Decimal) -> None:
    print(f"{Fore.WHITE}1 {symbol}={config.sym()}{price_ccy:0,.2f} {config.ccy}")
    if quantity:
        print(
            f"{Fore.WHITE}{quantity.normalize():0,f} {symbol}="
            f"{config.sym()}{quantity * price_ccy:0,.2f} {config.ccy}"
        )


def output_ds_price(asset_data: AsPriceRecord) -> None:
    if asset_data["price"] is None:
        raise RuntimeError("Missing price")

    print(
        f'{Fore.YELLOW}1 {asset_data["symbol"]}='
        f'{asset_data["price"].normalize():0,f} {asset_data["quote"]}'
        f'{Fore.CYAN} via {asset_data["data_source"]} ({asset_data["name"]})'
        f'{Fore.YELLOW + " <-" if asset_data.get("priority") else ""}'
    )


def output_assets(asset_list: List[AsRecord]) -> None:
    for asset_record in asset_list:
        if asset_record["asset_id"]:
            id_str = f' [ID:{asset_record["asset_id"]}]'
        else:
            id_str = ""

        print(
            f'{Fore.WHITE}{asset_record["symbol"]} ({asset_record["name"]})'
            f'{Fore.CYAN} via {asset_record["data_source"]}{id_str}'
            f'{Fore.YELLOW + " <-" if asset_record["priority"] else ""}'
        )


def validate_date(value: str) -> Timestamp:
    match = re.match(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})|([0-9]{2}\/[0-9]{2}\/[0-9]{4})$", value)

    if not match:
        raise argparse.ArgumentTypeError("date format is not valid, use YYYY-MM-DD or DD/MM/YYYY")

    if match.group(1):
        dayfirst = False
    else:
        dayfirst = True

    try:
        date = dateutil.parser.parse(value, dayfirst=dayfirst)
    except ValueError as e:
        raise argparse.ArgumentTypeError("date is not valid") from e

    return Timestamp(date.replace(tzinfo=TZ_UTC))


def validate_quantity(value: str) -> Decimal:
    try:
        quantity = Decimal(value.replace(",", ""))
    except InvalidOperation as e:
        raise argparse.ArgumentTypeError("quantity is not valid") from e

    return quantity


def datasource_choices(upper: bool = False) -> List[str]:
    if upper:
        return sorted([ds.__name__.upper() for ds in DataSourceBase.__subclasses__()])
    return sorted([ds.__name__ for ds in DataSourceBase.__subclasses__()])


if __name__ == "__main__":
    main()
