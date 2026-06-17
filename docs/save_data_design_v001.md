# Save Data Design v001

## コンセプト

本作は蓄積型の釣りシミュレーションである。

プレイヤーは同じ湖に通い、

- 地形を覚える
- 魚を釣る
- 釣果を記録する
- NPCから情報を得る
- 季節変化を経験する

ことで湖への理解を深めていく。

そのためセーブデータは単なる進行状況ではなく、

「プレイヤーが湖で積み重ねた記憶」

を保存する。

---

# 保存対象

## プレイヤー情報

```js
player = {
  name: "Player",

  money: 12000,

  anglerRank: 2,

  reputation: 35,

  currentMap: "tutorial_pond",

  currentPosition: {
    x: 12,
    y: 8
  }
}
```

---

# 所持品

## タックル

```js
tackle = {
  rods: [],
  reels: [],
  lines: []
}
```

---

## ルアー

```js
lures = [
  {
    id: "lure_001",
    name: "Shallow Crank",
    owned: true
  }
]
```

---

# 移動手段

```js
mobility = {
  bicycle: false,

  wader: false,

  rowBoat: false,

  bassBoat: false
}
```

---

# カレンダー

年は持たない。

---

```js
calendar = {
  month: 4,

  day: 18,

  time: "06:30",

  seasonPhase: "spring"
}
```

---

# 現在の環境

```js
environment = {
  weather: "cloudy",

  airTemp: 17.5,

  waterTemp: 14.8,

  windDirection: "south",

  windStrength: 3,

  waterLevel: 0.0,

  turbidity: "stain"
}
```

---

# 湖状態

湖ごとに保存。

---

```js
lakeState = {
  lakeId: "tutorial_pond",

  weedState: {},

  pressureMap: {},

  discoveredTiles: [],

  unlockedShoreTiles: []
}
```

---

# 発見済みポイント

プレイヤーが実際に訪れた場所。

---

```js
discoveredPoints = [
  {
    pointId: "north_cove_01",

    name: "北ワンド",

    discoveredDate: "04/18",

    notes: []
  }
]
```

---

# 水中情報

基本的には非表示。

ただしプレイヤーが発見した情報は保存。

---

例

```js
underwaterKnowledge = {
  pointId: "north_cove_01",

  knownStructures: [
    "fallen_tree",
    "weed_edge"
  ],

  knownDepthHints: [
    "沖が深い"
  ]
}
```

---

# 釣果履歴

本作の最重要保存データ。

---

```js
catchLog = [
  {
    date: "04/18",

    time: "06:42",

    lakeId: "tutorial_pond",

    pointId: "north_cove_01",

    weather: "cloudy",

    windDirection: "south",

    waterTemp: 14.8,

    lureId: "minnow_001",

    length: 42.3,

    weight: 1.25
  }
]
```

---

# 最大魚記録

```js
records = {
  personalBest: {
    length: 52.1,

    weight: 2.4,

    date: "06/12",

    lakeId: "small_reservoir",

    lureId: "jig_003"
  }
}
```

---

# 魚個体データ

40cm以上のみ個体管理。

---

```js
managedFish = [
  {
    id: "B40012",

    lakeId: "small_reservoir",

    length: 47.2,

    weight: 1.92,

    age: 5,

    homeArea: "north_cove",

    lastCaughtDate: null
  }
]
```

---

# 50cm以上

重要個体として履歴保存。

---

```js
trophyFish = [
  {
    id: "B50001",

    lakeId: "main_lake",

    length: 54.6,

    weight: 3.1,

    age: 7,

    knownByPlayer: false
  }
]
```

---

# レジェンド個体

プレイヤーには明示しない。

---

```js
legendFish = [
  {
    id: "L001",

    lakeId: "main_lake",

    length: 63.4,

    weight: 5.8,

    age: 11,

    active: true
  }
]
```

---

# 群集魚データ

40cm未満。

---

```js
fishPopulation = {
  small: {
    population: 1200,

    averageLength: 18.5
  },

  medium: {
    population: 650,

    averageLength: 31.2
  }
}
```

---

# NPC情報

```js
npcState = {
  npcId: "local_oldman_01",

  friendship: 25,

  knownTopics: [
    "north_cove_big_fish"
  ],

  lastTalkDate: "04/17"
}
```

---

# 会話ログ

```js
conversationLog = [
  {
    date: "04/17",

    npcId: "local_oldman_01",

    topic: "北ワンドに大きい魚がいるらしい"
  }
]
```

---

# 噂情報

```js
rumors = [
  {
    id: "rumor_001",

    date: "04/16",

    sourceNpc: "shop_owner",

    content: "東岬で50アップが出た",

    truthLevel: "unknown"
  }
]
```

---

# 釣果掲示板

日々更新。

---

```js
catchBoard = [
  {
    date: "04/18",

    lakeId: "main_lake",

    pointName: "東岬",

    length: 49.0,

    lureCategory: "crank"
  }
]
```

---

# 大会実績

```js
tournamentRecords = [
  {
    tournamentId: "local_cup_01",

    date: "04/20",

    rank: 3,

    totalWeight: 3.2,

    biggestFish: 41.5
  }
]
```

---

# 解放状態

```js
unlocks = {
  maps: [
    "tutorial_pond",
    "farm_ponds"
  ],

  shops: [
    "local_tackle_shop"
  ],

  tournaments: [
    "local_cup"
  ]
}
```

---

# プレイヤーメモ

任意メモ。

---

```js
playerNotes = [
  {
    date: "04/18",

    pointId: "north_cove_01",

    text: "朝はミノーに反応あり"
  }
]
```

---

# 保存頻度

## 自動保存

発生タイミング

```text
日付変更時

釣果記録時

大会終了時

マップ移動時

ショップ購入時
```

---

## 手動保存

拠点・自宅で可能。

---

# 設計方針

セーブデータは単なる進行状況ではない。

プレイヤーの釣行記録、
湖の記憶、
魚との出会い、
NPCから得た情報を保存する。

本作におけるセーブデータとは、

「プレイヤーだけの釣り人生ログ」

である。