---
title: Add calculated fields and summary tables
group: How to
order: 9
---
Calculated fields add engineering quantities to every load. Summary tables total them up.

## 1. Bring in what the formulas need

The formulas below use a power factor and an efficiency. Either:

- map them from the MEL: in **Edit fields…** add number fields *Power factor* (`pf`) and *Efficiency* (`eff`), then map the MEL's columns to them in the import's **Mapping** tab; or
- use the matched motor's figures, `<<Motor.PF100>>` and `<<Motor.Eff100>>`, which need the load's **Poles** field mapped.

## 2. Add a calculated field

1. Open **Project lists → Load List** and press **Edit fields…**.
2. Press **+ Add calculated field** and name it *Active power kW*.
3. Press **ƒ Formula…** and fill in:
   - **Applies when**: `<<load_rating>> != ''`
   - **Formula**: `<<load_rating>> * 0.746 / <<eff>> if <<units>> == 'HP' else <<load_rating>> / <<eff>>`
   - **Decimals**: 2
4. Press **▶ Try it on the Load List** and look at the answers. Rows with problems are listed first.
5. Press **Save…**, then **Confirm and save**.

![A calculated field](img/load-calculated-field.png)

## 3. Build on it

Each field can use the ones before it, by key:

| Field | Formula |
|---|---|
| Apparent power kVA | `<<active_power_kw>> / <<pf>>` |
| Reactive power kVAr | `sqrt(<<apparent_power_kva>>**2 - <<active_power_kw>>**2)` |
| Rated current A | `<<apparent_power_kva>> * 1000 / (sqrt(3) * <<voltage>>)` |
| Average kW | `<<active_power_kw>> * <<LoadFactor.NameplateLF>> * <<LoadFactor.AvgDemand>>` |
| Annual consumption kWh | `<<active_power_kw>> * <<utility_factor>> * <<diversity_factor>> * 8760` |

## 4. Add checks

A check flags an answer that cannot be right. On *Power factor*-based fields, for example:

- Check `0 < <<value>> <= 1`, as an **error**, with the message "Power factor must be between 0 and 1".

A cell that fails shows ⛔ or ⚠ in the Load List, with the message as its tooltip.

## 5. Use the fields

- They are columns of the Load List, marked ƒ.
- They are tags in load types' rows: `<<rated_current_a>>`.
- A load type's [component table](help:load-types#components) can be matched on one, for example a circuit breaker chosen by rated current.
- They can be columns of a Load List deliverable.

## 6. Total them in a summary table

1. Open **Project master lists → Load List Summary** and press **Edit tables**, then **+ Table**.
2. Name it *Transformer loading*, with the filter `not <<ispanel>>`.
3. Add a row for each transformer: name `TX-1`, condition `'TX-1' in <<supplychain>>`, reference load `TX-1`.
4. Add columns:
   - **+ Total column**: *Total kW*, Sum of *Active power kW*.
   - **+ Total column**: *Total kVA*, Sum of *Apparent power kVA*.
   - **+ Formula column**: *Loading %*, formula `<<Total kVA>> / <<Ref.load_rating>> * 100`, 1 decimal, with a warning check `<<value>> <= 80`.
5. Press **▶ Preview**, then **Save**.

![Editing a summary table](img/load-summary-edit.png)

Reference: [Load List](help:load-list#calculated-fields), [Load List Summary](help:load-summary).
