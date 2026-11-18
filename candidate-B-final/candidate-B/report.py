"""Расчёт выплат подрядчикам на конец выбранного дня."""

import argparse
import csv
import re
from datetime import date
from pathlib import Path


def rows(folder, name):
    with (folder / name).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def kopecks(value):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise ValueError(f"Некорректная денежная сумма {value!r}")
    whole, _, fraction = value.partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0"))


def rubles(value):
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 100)
    formatted = f"{whole:,}".replace(",", " ")
    return f"{sign}{formatted},{fraction:02}"


def reached(value, day):
    return bool(value) and date.fromisoformat(value) <= day


def build_report(folder, day):
    contracts = rows(folder, "contracts.csv")
    works = rows(folder, "works.csv")
    payments = rows(folder, "payments.csv")
    lines = [f"# Расчёты с подрядчиками на {day:%d.%m.%Y}", ""]
    for contract in contracts:
        if not reached(contract["signed_at"], day):
            continue
        cid = contract["contract_id"]
        items = [w for w in works if w["contract_id"] == cid]
        paid = dict.fromkeys((w["work_id"] for w in items), 0)
        advance = 0
        for p in payments:
            if p["contract_id"] != cid or not reached(p["paid_at"], day):
                continue
            if reached(p["refunded_at"], day):
                continue
            amount = kopecks(p["amount"])
            if p["work_id"]:
                paid[p["work_id"]] += amount
            else:
                advance += amount
        net = sum(paid.values()) + advance
        accepted = [w for w in items if reached(w["completed_at"], day)
                    and not reached(w["cancelled_at"], day)]
        for w in sorted(accepted, key=lambda w: (w["completed_at"], w["work_id"])):
            wid = w["work_id"]
            allocation = min(advance, max(0, kopecks(w["price"]) - paid[wid]))
            paid[wid] += allocation
            advance -= allocation

        lines.extend([f'## {cid} — {contract["contractor"]}', "",
                      "| Работа | Статус | Цена, ₽ | Зачтено в цену работы, ₽ | Остаток цены работы, ₽ |",
                      "|---|---|---:|---:|---:|"])
        active_price = remaining = due = 0
        cancelled_items = []
        has_planned = False
        for w in items:
            wid = w["work_id"]
            price = kopecks(w["price"])
            cancelled = reached(w["cancelled_at"], day)
            accepted_now = reached(w["completed_at"], day) and not cancelled
            status = "Отменена" if cancelled else "Принята" if accepted_now else "В плане"
            if cancelled:
                cancelled_items.append((wid, price))
            elif not accepted_now:
                has_planned = True
            active_price += 0 if cancelled else price
            left = 0 if cancelled else max(0, price - paid[wid])
            remaining += left
            due += left if accepted_now else 0
            title = w["title"].replace("|", r"\|").replace("\n", " ")
            lines.append(f"| {wid} · {title} | {status} | {rubles(price)} | "
                         f"{rubles(paid[wid])} | {rubles(left)} |")
        face = kopecks(contract["amount"])
        if has_planned:
            lines.extend(["", "Остаток цены плановой работы при её приёмке можно покрыть "
                          "свободным авансом или новым перечислением."])
        if cancelled_items:
            cancelled_details = ", ".join(f"{wid} ({rubles(price)} ₽)" for wid, price in cancelled_items)
            lines.extend(["", f"Отменённые работы указаны с исходной ценой: {cancelled_details}. "
                          "Компенсация за отмену принята равной нулю до подтверждения бухгалтером."])
        future_due = max(0, remaining - advance)
        totals = [
            ("Осталось доплатить за уже принятые работы", due),
            ("Сумма подписанного договора", face),
            ("Цена действующих работ", active_price),
            ("Выплачено по договору за вычетом возвратов", net),
            ("Из них отнесено на работы", sum(paid.values())),
            ("Уже перечислено, пока не зачтено в работы (свободный аванс)", advance),
            ("Остаток цены всех действующих работ до зачёта свободного аванса", remaining),
            ("Предстоит перечислить, если все действующие работы будут приняты", future_due),
            ("Для сверки: сумма договора по выгрузке минус выплаты за вычетом возвратов", face - net),
        ]
        if net > active_price:
            totals.append(("Переплата сверх цены всех действующих работ", net - active_price))
        lines.extend(["", "| Итог | Рубли |", "|---|---:|"])
        lines.extend(f"| {label} | {rubles(value)} |" for label, value in totals)
        cancelled_total = sum(price for _, price in cancelled_items)
        if cancelled_total and face - active_price == cancelled_total:
            lines.extend(["", f"По действующим работам потребуется перечислить ещё {rubles(future_due)} ₽ "
                          f"(из оставшихся {rubles(remaining)} ₽ аванс покроет {rubles(min(remaining, advance))} ₽). "
                          f"Для сверки с договором: {rubles(face)} − {rubles(net)} = {rubles(face - net)} ₽. "
                          f"В указанную в выгрузке сумму договора входят отменённые работы на "
                          f"{rubles(cancelled_total)} ₽. Сведений об изменении договора нет."])
        lines.append("")
    if len(lines) == 2:
        lines.append("На эту дату подписанных договоров нет.")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat, metavar="ГГГГ-ММ-ДД")
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--output", type=Path, help="Сохранить отчёт Markdown в UTF-8")
    args = parser.parse_args()
    report = build_report(args.data, args.date)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report, end="")
