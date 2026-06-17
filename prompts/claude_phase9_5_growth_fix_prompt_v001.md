# Phase 9.5 Fish Growth Fix

Phase 9レビューの結果、Fish Growth System が未完成です。

Phase 10へ進む前に、Fish Growth を完成させてください。

---

# 問題点

現在

- age は存在する
- memory は更新される
- caution は更新される

しかし

- fish length が成長しない
- weight が変化しない
- genetics が成長へ影響していない

状態です。

このため

47cm
↓
1年後
↓
47cm

になっています。

本来の設計は

47cm
↓
1年後
↓
51cm

です。

---

# 実装内容

## FishIndividual 拡張

追加フィールド

```python
genetic_max_size: float
growth_rate: float
health: float
```

---

## 初期生成

initialize_spot()

追加

```python
genetic_max_size =
    length + random(3.0, 12.0)

growth_rate =
    random(0.003, 0.030)

health = 1.0
```

---

## daily_growth()

FishIndividual に追加

```python
def daily_growth(self):
```

処理

```python
self.age += 1

if self.length >= self.genetic_max_size:
    return

remaining =
    self.genetic_max_size - self.length

growth =
    self.growth_rate
    * remaining
    * 0.10
    * self.health

self.length += growth

self.weight =
    _weight_kg(self.length)
```

---

## PopulationManager

追加

```python
update_growth()
```

処理

```python
for fish in managed_fish:
    fish.daily_growth()
```

---

## game.py

日付切り替え時

現在

```python
population.update_memory()
```

↓

変更

```python
population.update_growth()
population.update_memory()
```

---

# F2デバッグ強化

現在

```text
B51003
51.2cm
```

↓

変更

```text
B51003
51.2 / 58.7
```

表示内容

```text
現在サイズ
最大サイズ
```

---

# Save対応

to_dict()

追加

```python
genetic_max_size
growth_rate
health
```

---

from_dict()

追加

```python
genetic_max_size
growth_rate
health
```

---

# 忘却率調整

現在

```python
loss_rate = 0.005
```

↓

変更

```python
loss_rate = 0.010
```

理由

魚が1年近く記憶し続けるため。

数か月でかなり忘れる程度へ調整する。

---

# 動作確認

以下を確認してください。

1.

40cm魚

↓

100日後

↓

サイズ増加

2.

最大サイズ到達後

↓

成長停止

3.

セーブ

↓

ロード

↓

サイズ維持

4.

F2

↓

現在サイズ/最大サイズ表示

---

# 設計方針

魚は生きている。

時間経過で成長し、

学習し、

忘却する。

Phase 10 Catch & Release の前提として、

「去年より大きくなった魚」

が成立する状態にしてください。
