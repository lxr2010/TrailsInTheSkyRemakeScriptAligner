import pandas as pd
from collections import Counter
import json
import matplotlib.pyplot as plt
import seaborn as sns

def plot_gap_heatmap(df_dist):
    # 过滤掉极端的长尾数据（比如 gap > 20 的），只看核心分布
    filtered_df = df_dist[(df_dist['gap_a'] < 15) & (df_dist['gap_b'] < 15)]
    
    # 透视表化
    pivot_table = filtered_df.pivot(index='gap_a', columns='gap_b', values='count').fillna(0)
    
    plt.figure(figsize=(10, 8))
    sns.heatmap(pivot_table, annot=True, fmt=".0f", cmap="YlGnBu")
    plt.title("Gap_A vs Gap_B Distribution")
    save_path = "gap_distribution.png"
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"图表已保存至: {save_path}")
    plt.close() # 记得关闭，释放内存


def analyze_gap_distribution(confirmed_anchors):
    """
    confirmed_anchors: List of (pos_a, pos_b) sorted by pos_a
    """
    with open("gaps.json", "r", encoding="utf-8") as f:
      gaps = json.loads(f.read())

    gaps = [(g[2] - g[0],g[3] - g[1]) for g in gaps]
    
    # 使用 Counter 统计频次
    dist = Counter(gaps)
    
    # 转换为 DataFrame 方便观察
    df_dist = pd.DataFrame([
        {'gap_a': k[0], 'gap_b': k[1], 'count': v} 
        for k, v in dist.items()
    ])
    
    # 按频次排序
    df_dist = df_dist.sort_values(by='count', ascending=False).reset_index(drop=True)
    
    # 计算百分比
    total = df_dist['count'].sum()
    df_dist['percentage'] = (df_dist['count'] / total * 100).round(2)
    
    return df_dist

# 示例调用
# dist_table = analyze_gap_distribution(confirmed_anchors)
# print(dist_table.head(20))

if __name__ == "__main__":
    dist_table = analyze_gap_distribution([])
    dist_table.to_csv("gap_distribution.csv", index=False)

    print(dist_table.head(20))
    # plot_gap_heatmap(dist_table)
  