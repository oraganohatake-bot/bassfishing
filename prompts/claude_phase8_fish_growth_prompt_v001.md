Phase 7確認しました。

次は Phase 8 として Fish Growth System を実装してください。

目的:
大型魚が時間経過で成長する世界を作る。

実装内容:

1. FishIndividual拡張

追加:

- birth_day
- health
- growth_rate
- genetics

2. 成長

毎日

length += growth_amount

weight 再計算

3. 成長速度

小型ほど早い

大型ほど遅い

例

40cm:
+0.02cm/day

50cm:
+0.01cm/day

60cm:
+0.003cm/day

4. genetics

0.8〜1.2

成長補正

5. carrying capacity

スポットごとに設定

- poor
- normal
- rich

richスポットは大型化しやすい

6. 老衰

年齢上限

10〜15年

超過で死亡確率発生

7. 自然死亡

毎日微小確率

8. 世代交代

死亡時

若魚補充

9. 50cm到達イベント

初回突破時

内部フラグ

10. レジェンド候補

60cm以上

legend_candidate = true

11. Save連携

全フィールド保存

12. F2デバッグ拡張

表示

- age
- growth_rate
- genetics
- days_alive

13. README更新

まだNPC・大会・ボート・ショップは実装しないでください。
