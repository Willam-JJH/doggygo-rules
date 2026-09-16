# doggygo-rules

狗狗加速 iOS 官方客户端的**自定义分流规则**，通过「远程规则」的方式加载。

## 为什么需要这个仓库

狗狗加速的 iOS 官方客户端是 **sing-box 内核**，它的配置由机场订阅下发，本身已经会「国内直连、国外走代理」，但：

- 没有广告拦截
- 微软 / 苹果 / Google 一批应该直连的域名会被送去代理
- 你在 Clash 上攒的那些直连白名单（学校站点、竞赛站、开发工具 CDN…）一条都不生效

这个仓库把那些规则转成 sing-box 的远程规则集，由客户端按 URL 拉取。

## 客户端的能力边界（决定了规则怎么组织）

| | Clash (Windows) | 这个 iOS 客户端 |
|---|---|---|
| 出站策略 | 任意策略组：🇺🇸美国节点 / 🔥ChatGPT / 专线… | **只有三种**：代理 / 直连 / reject |
| 规则结构 | 一份 prepend 列表，按顺序匹配 | 每个规则集**绑定一种出站**，规则集内只写匹配条件 |
| 匹配类型 | DOMAIN / DOMAIN-SUFFIX / DOMAIN-KEYWORD / IP-CIDR / PROCESS-NAME… | DOMAIN / DOMAIN-SUFFIX / DOMAIN-KEYWORD / IP-CIDR（**没有进程匹配**） |

由此产生两个结论：

1. **按出站拆成三份规则集**，而不是照搬 Clash 的顺序列表。
2. **区域精细分流做不到**。Clash 上「codeforces 走俄罗斯、atcoder 走日本、claude 走美国」在 iOS 上只能统一成「代理」——除非你在客户端里把某个具体节点钉死，但机场一改节点名就失效，不建议。

## 仓库结构

```
singbox/          ← 客户端要引用的就是这里的 URL
  direct.json     119 条  「直连」
  reject.json      33 条  「reject」
  proxy.json      123 条  「代理」
text/             ← 同样内容的纯文本格式，万一客户端不认 JSON 可以拿来试
tools/convert.py  ← 从本机 Clash 配置重新生成上面这些文件
```

## 在 App 里怎么配

「自定义规则 → 远程规则」，**添加三条**：

| 名字 | URL | 代理方式 |
|---|---|---|
| `direct` | `https://testingcf.jsdelivr.net/gh/Willam-JJH/doggygo-rules@main/singbox/direct.json` | 直连 |
| `ads` | `https://testingcf.jsdelivr.net/gh/Willam-JJH/doggygo-rules@main/singbox/reject.json` | reject |
| `proxy` | `https://testingcf.jsdelivr.net/gh/Willam-JJH/doggygo-rules@main/singbox/proxy.json` | 代理 |

### 两个坑

- **必须用 jsdelivr，不要用 `raw.githubusercontent.com`**：raw 在国内直连不通，客户端拉不到规则。机场自己的 `geoip-cn` / `geosite-cn` 用的也是 `testingcf.jsdelivr.net`。
- **jsdelivr 对分支名有缓存**（`@main` 最长约 12 小时）。改完规则想立刻生效，把 URL 里的 `@main` 换成那次提交的 commit SHA。

### 只想用一个规则集的话

`direct.json` 收益最大，先加它也能跑。`proxy.json` 通常可有可无——客户端默认就是「没匹配到的走代理」，它只是兜底。

## 广告拦截：更省事的做法

`reject.json` 是从你现有 Clash 配置里搬过来的 29 条（机场订阅自带的那批 + 你后来加的），覆盖的是常见国内广告联盟。想更彻底，可以直接再加一条远程规则，用官方通用规则集：

```
名字:   ads-all
URL:    https://testingcf.jsdelivr.net/gh/SagerNet/sing-geosite@rule-set/geosite-category-ads-all.srs
代理方式: reject
```

这是 sing-box 官方维护的二进制规则集（`.srs`），和客户端自带的 `geoip-cn` 同源，覆盖面比我们这份手工名单大得多，而且会自动更新。

## 没搬过来的东西（以及为什么）

| 类别 | 数量 | 原因 |
|---|---|---|
| `PROCESS-NAME` / `PROCESS-PATH` | 约 40 条 | iOS 没有进程匹配：Steam、微信、Code.exe、洋葱学园这些规则在手机上无意义 |
| `DOMAIN-KEYWORD,google` / `anthropic` | 2 条 | 客户端默认 `final: proxy` 已经覆盖；而且 `google` 关键字会把 `google.cn`（要直连）一起吃掉 |
| 指向区域组的规则 | — | 已合并进「代理」，见上文能力边界 |
| `IP-CIDR6,…` | 1 条 | 客户端 IPv6 未启用，永不匹配 |

## 规则更新流程

改完规则后重新生成：

```powershell
python tools\convert.py
git add -A
git commit -m "update rules"
git push
```

`convert.py` 默认从本机 Clash Verge 的 profile 目录读取：

```
%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\profiles\
  r653jeIRqabx.yaml   你的 rules profile（prepend/append/delete）
  mVbTqfK59P2y.yaml   merge profile（prepend-rules）
  RHOPK3Eusk7y.yaml   机场订阅（只取其中的 REJECT 规则）
```

换机器或想在别处跑，把目录作为参数传进去：`python tools/convert.py <目录>`。

生成时会打印每一类丢弃了什么，**丢弃项值得看一眼**——如果本机 Clash 里新增了域名规则，这里应该能对上数量。

## 注意

- 仓库里**只有规则，没有节点信息、没有订阅链接**，所以可以设为 public（jsdelivr 也只支持 public 仓库）。
- 规则集本身不含出站策略，出站是你在 App 里添加时选的那一项。所以同一份 `direct.json` 你也可以挂成「代理」用——只是没意义。
- 如果某个网站突然打不开，先怀疑 `reject.json` 里的宽关键字规则误伤。其中 `DOMAIN-KEYWORD,usage` 是机场订阅自带的，范围特别宽（任何含 "usage" 的域名都会被拦），有问题优先删它。
