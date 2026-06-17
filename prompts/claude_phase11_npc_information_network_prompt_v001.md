# Phase 11 NPC Information Network

Phase 10確認しました。

次は Phase 11 として NPC Information Network を実装してください。

---

# 目的

NPCを単なるヒント発生装置ではなく、

湖を観察している住人として実装する。

NPCは実在する魚、
実際の環境変化、
実際の釣果情報を元に会話する。

---

# 実装内容

## npc_manager.py

新規作成

管理クラス

```python
NPCManager
```

---

保持

```python
npcs
rumors
conversations
```

---

# NPC種別

実装

```text
Child

Beginner

Local

Veteran

ShopOwner
```

---

# NPC基本情報

```python
npc_id

name

type

home_spot

skill_level

friendship
```

---

# skill_level

Child

```text
0.2
```

---

Beginner

```text
0.4
```

---

Local

```text
0.7
```

---

Veteran

```text
0.9
```

---

ShopOwner

```text
0.8
```

---

# 観測システム

毎日

NPCは

```text
自宅周辺

お気に入りポイント
```

を観察する。

---

観測対象

```text
大型魚

レジェンド候補

釣果

環境変化
```

---

例

```text
B54002

54.2cm

North Cove
```

---

観測成功時

NPC知識へ登録

---

# NPC知識

```python
known_fish

known_spots

known_weather_patterns

known_catches
```

---

# 情報精度

NPCごとに異なる。

---

Child

```text
低精度
```

---

例

```text
大きい魚いた！
```

---

Veteran

```text
高精度
```

---

例

```text
北ワンドの沈み木に
50アップが付いている
```

---

# 噂システム

毎日生成。

---

情報源

```text
実魚

実釣果

環境変化
```

---

種類

```text
FishRumor

SpotRumor

WeatherRumor
```

---

例

```text
東岬で50アップ
```

---

例

```text
最近北岸にベイト
```

---

# 情報劣化

伝言ゲーム。

---

NPC間伝播時

```python
accuracy *= 0.95
```

---

例

実際

```text
54.2cm
```

↓

噂

```text
55cm
```

↓

さらに伝播

```text
60cm
```

---

# 会話

探索マップで

```text
E
```

会話。

---

表示

```text
1日1回
```

まで。

---

# 会話内容

優先順位

```text
大型魚

環境変化

釣果

一般情報
```

---

# 友好度

追加

```python
friendship
```

---

初期

```text
0
```

---

会話

```text
+1
```

---

魚を見せる

```text
+3
```

---

大会成績

```text
+5
```

将来利用。

---

# 友好度効果

0〜20

```text
一般情報
```

---

20〜50

```text
具体的スポット
```

---

50〜80

```text
大型魚情報
```

---

80〜100

```text
秘密ポイント
```

---

# 実魚参照

重要。

---

NPCは実際の個体を話題にする。

---

例

```text
北ワンドに
54cmくらいの魚がいる
```

↓

内部

```python
fish_id = B54002
```

---

# レジェンド候補

60cm以上

---

NPCは特別反応。

---

例

```text
最近妙な魚の話を聞く
```

---

```text
誰も釣れない魚だ
```

---

# NPC日誌

保存

```python
npc_observation_log
```

---

内容

```text
日時

魚

場所

内容
```

---

# Save連携

保存対象

```python
friendship

known_fish

known_spots

rumors

conversation_history
```

---

# UI

探索マップ

---

近づく

```text
Talk [E]
```

---

会話ウィンドウ

実装。

---

# デバッグ

F3

表示

```text
NPC名

友好度

知っている魚数

知っているスポット数

噂数
```

---

# README更新

追加

```text
NPC System

Rumor System

Friendship

Information Accuracy
```

---

# 設計方針

NPCは攻略Wikiではない。

湖で暮らす人間である。

プレイヤーは魚を探すだけでなく、

人と話し、

噂を集め、

情報を検証しながら湖を理解する。

最終目標は、

NPCが

「去年見た魚」

を覚えている世界である。
