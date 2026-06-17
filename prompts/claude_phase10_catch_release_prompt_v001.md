# Phase 10 Catch & Release System

Phase 9確認しました。

次は Phase 10 として Catch & Release System を実装してください。

---

# 目的

魚を消費リソースではなく、

湖の中で生き続ける個体として扱う。

プレイヤーは魚を釣った後、

キープするか、
リリースするかを選択できる。

リリースされた魚は成長し、
学習し、
将来再び釣れる可能性がある。

本作の目標は、

「去年釣った魚と再会する体験」

を作ることである。

---

# 実装内容

## キャッチ画面

魚をキャッチした後、

結果画面で選択肢を表示。

```text
[K] KEEP

[R] RELEASE
```

---

## KEEP

魚を持ち帰る。

処理

```text
個体削除

釣果保存

報酬獲得
```

---

報酬

```python
reward =
 weight * species_value
```

---

MVP

```python
reward = length_cm * 10
```

---

例

```text
50cm

↓

500pt
```

---

## RELEASE

魚を湖へ返す。

処理

```text
個体維持

釣果保存

履歴更新
```

---

報酬

```text
なし
```

---

# FishIndividual拡張

追加フィールド

```python
release_count

last_release_day
```

---

初期値

```python
release_count = 0
```

---

## リリース時

```python
release_count += 1

last_release_day = current_day
```

---

# リリースペナルティ

リリース直後。

---

```python
health -= 0.05

caution += 0.05
```

---

上限

```python
caution <= 1.0
```

---

下限

```python
health >= 0.1
```

---

# 再捕獲システム

重要。

---

同一 fish_id を再度釣った場合。

---

表示

```text
RECAPTURE
```

---

例

```text
RECAPTURE

B51003

53.2cm
```

---

# FishHistory

新規追加。

---

保持

```python
fish_id

first_caught_day

last_caught_day

total_catches

total_releases

best_length
```

---

# 初回捕獲

```python
first_caught_day = current_day
```

---

# 再捕獲

```python
total_catches += 1

last_caught_day = current_day
```

---

# リリース

```python
total_releases += 1
```

---

# 個体履歴

FishPopulationManager

追加

```python
fish_history
```

---

例

```python
{
    "B51003": {
        ...
    }
}
```

---

# Catch Log

追加保存

```python
fish_id

action
```

---

例

```python
B51003

53.2cm

RELEASE
```

---

例

```python
B52007

52.1cm

KEEP
```

---

# Save連携

保存対象

```python
release_count

last_release_day

fish_history
```

---

# F2デバッグ拡張

追加表示

```text
ReleaseCount

LastRelease

History
```

---

例

```text
B51003

53.2cm

Release 4

Caught 7
```

---

# キャッチ画面

追加表示

---

例

```text
B51003

53.2cm

Age 7

Release 4
```

---

# 再捕獲演出

同一魚の場合。

---

表示

```text
★ RECAPTURE ★
```

---

例

```text
Last caught:
04/12

Length:
52.4cm

Now:
53.2cm
```

---

# README更新

追加

```text
Catch & Release

Fish History

Recapture

Reward System
```

---

# 設計方針

魚はアイテムではない。

魚は湖で生き続ける。

プレイヤーは

キープするか、

未来へ残すかを選択する。

目標は、

「去年リリースした魚と再会した」

という体験を生み出すことである。

本作における最大の報酬は、

ポイントではなく、

湖の歴史に参加することである。
