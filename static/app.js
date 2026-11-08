"use strict";
const $ = id => document.getElementById(id);
const main = $("app");
let cards = {},
  room = null,
  ws = null,
  session = null,
  busy = false,
  timer;
const colors = ["#b43d34", "#17674f", "#594b96", "#bf6612", "#147a96", "#a43875", "#565c32", "#3c6593"];

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function add(parent, ...nodes) {
  parent.append(...nodes);
  return parent;
}

function btn(label, fn, cls = "") {
  const b = el("button", cls, label);
  b.type = "button";
  b.onclick = fn;
  return b;
}

function toast(msg) {
  $("notice").textContent = msg;
  $("notice").hidden = false;
  clearTimeout(timer);
  timer = setTimeout(() => {
    $("notice").hidden = true;
  }, 4700);
}

function picture(name, cls = "") {
  const img = el("img", cls);
  img.src = "/assets/" + encodeURIComponent(name) + ".webp";
  img.alt = name;
  return img;
}

function dialog(title, ...nodes) {
  $("book").querySelector("h2").textContent = title;
  $("book-body").replaceChildren(...nodes);
  $("book").showModal();
}
$("close-book").onclick = () => $("book").close();
$("rules").onclick = () => dialog("比赛规则",
  ...["每局四轮，第二名角色冲线时本轮结束。金奖杯依次值 3、4、4、5 分，银奖杯值 1、2、2、3 分。星星与能力得分也计入总分。",
    "从 2 倍玩家人数的角色中顺时针选一遍，再逆时针选一遍。三人及以上每轮派一名，每两轮重新选角。两人局每轮各派两名，指定行动顺序并分配两枚骰子，每轮重新选角。",
    "通常掷一枚六面骰。按游戏开始、掷骰前、主要移动、落点效果、自己能力、顺时针其他角色能力的顺序结算。卡面注明的时机生效。",
    "标准地图的数字标示距离。狂热地图中星星得 1 分，TRIP 跳过下一次主要移动，箭头按指向移动。移动、传送和放置产生的新落点都触发地图。",
    "最终按总分排名，同分比四轮平均名次（越小越好）。双角色取本轮最佳名次，未冲线按位置，同格并列。"
  ].map(t => el("p", "", t)));
async function api(path, data, token) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? {
        Authorization: "Bearer " + token
      } : {})
    },
    body: JSON.stringify(data)
  });
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === "string" ? result.detail : "请求无效，请检查输入");
  return result;
}

function field(title, input) {
  return add(el("label", "", title), input);
}

function form(title, fields, label, submit) {
  const f = add(el("form", "panel stack"), el("h2", "", title), ...fields);
  const b = el("button", "primary", label);
  f.append(b);
  f.onsubmit = async e => {
    e.preventDefault();
    b.disabled = true;
    try {
      await submit();
    } catch (err) {
      toast(err.message);
    } finally {
      b.disabled = false;
    }
  };
  return f;
}

function card(name, choose) {
  const b = btn("", choose || (() => dialog(name, picture(name, "portrait"), el("p", "", cards[name].join(" · ")))), "card");
  b.title = cards[name][1];
  return add(b, picture(name), el("strong", "", name), el("small", "", cards[name][0]));
}

function home() {
  const hero = add(el("section", "hero"), add(el("div"), el("p", "eyebrow", "MAGICAL ATHLETE"),
      el("h1", "", "魔法运动会"), el("p", "sub", "四轮骰子竞速 · 支持真人与电脑同场")),
    add(el("div", "fan"), ...["模仿猫", "教练", "起哄者"].map(n => picture(n))));
  const name = el("input");
  name.required = true;
  name.maxLength = 20;
  name.placeholder = "你的昵称";
  const guest = name.cloneNode();
  const code = el("input");
  code.required = true;
  code.maxLength = 6;
  code.placeholder = "6 位房间码";
  const board = el("select");
  for (const n of ["标准地图", "狂热地图"]) board.add(new Option(n, n));
  const create = form("创建房间", [field("玩家昵称", name), field("比赛地图", board)], "创建房间", async () => {
    enter(await api("/api/rooms", {
      name: name.value.trim(),
      board: board.value
    }));
  });
  const join = form("加入比赛", [field("玩家昵称", guest), field("房间码", code)], "加入房间", async () => {
    enter(await api("/api/rooms/" + encodeURIComponent(code.value.trim().toUpperCase()) + "/join", {
      name: guest.value.trim()
    }));
  });
  main.replaceChildren(hero, add(el("div", "homegrid"), create, join),
    add(el("section", "section"), el("h2", "", "角色图鉴"), add(el("div", "card-grid"), ...Object.keys(cards).map(n => card(n)))));
  const saved = savedSeat();
  if (saved) hero.after(add(el("div", "section"), btn("回到房间 " + saved.code, () => enter(saved), "primary")));
}

function savedSeat() {
  try {
    return JSON.parse(localStorage.getItem("athlete-seat"));
  } catch {
    return null;
  }
}

function enter(s) {
  session = s;
  localStorage.setItem("athlete-seat", JSON.stringify(s));
  main.replaceChildren(add(el("section", "panel section"), el("h2", "", "正在连接房间…")));
  connect();
}

function connect() {
  if (!session) return;
  const socket = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/" + session.code);
  ws = socket;
  socket.onopen = () => socket.send(JSON.stringify({
    token: session.token
  }));
  socket.onmessage = e => {
    if (ws !== socket) return;
    room = JSON.parse(e.data);
    busy = false;
    draw();
  };
  socket.onclose = e => {
    if (ws !== socket) return;
    if (e.code === 1008) {
      leave(true);
      toast("房间或座位凭证已失效");
      return;
    }
    busy = true;
    if (room) draw();
    toast("连接中断，正在重连…");
    setTimeout(() => {
      if (ws === socket) connect();
    }, 1200);
  };
}

function leave(forget = false) {
  const prev = ws;
  ws = null;
  if (prev) prev.close();
  if (forget) localStorage.removeItem("athlete-seat");
  session = null;
  room = null;
  busy = false;
  home();
}
async function act(action, value = "") {
  if (busy || !session || ws.readyState !== WebSocket.OPEN) return;
  busy = true;
  draw();
  try {
    await api("/api/rooms/" + session.code + "/actions", {
      action,
      value,
      revision: room.revision
    }, session.token);
  } catch (err) {
    toast(err.message);
    busy = false;
    draw();
  }
}

function actButton(label, action, value = "", cls = "") {
  const b = btn(label, () => act(action, value), cls);
  b.disabled = busy;
  return b;
}

function dot(seat) {
  const d = el("i", "dot");
  d.style.setProperty("--team", colors[seat]);
  return d;
}

function raceBoard() {
  const name = room.board,
    wild = name === "狂热地图";
  const board = add(el("div", "board"), picture(name));
  const locations = {};
  for (const [c, p] of Object.entries(room.pieces)) {
    (locations[p.pos] ||= []).push(c);
  }
  for (const [index, names] of Object.entries(locations)) {
    const pos = Number(index);
    let x, y;
    if (pos === 0) {
      x = 11.5;
      y = 17;
    } else if (pos === 30) {
      x = 5.5;
      y = 51;
    } else if (pos <= 12) {
      x = (wild ? 24.7 : 24.6) + (pos - 1) * (wild ? 6.26 : 6.45);
      y = 17;
    } else if (pos <= 14) {
      x = wild ? 93.3 : 95.5;
      y = pos === 13 ? 38 : 59;
    } else {
      x = (wild ? 93.3 : 95.5) - (pos - 15) * (wild ? 6.25 : 6.48);
      y = 82;
    }
    names.forEach((c, i) => {
      const p = room.pieces[c],
        pawn = el("span", "pawn", c.slice(0, 1));
      pawn.title = c + " · " + room.players[p.seat].name;
      pawn.style.left = (x + ((i % 2) - (names.length > 1 ? 0.5 : 0)) * 2.5) + "%";
      pawn.style.top = (y + (Math.floor(i / 2) - Math.floor((names.length - 1) / 2) / 2) * 7) + "%";
      pawn.style.setProperty("--team", colors[p.seat]);
      board.append(pawn);
    });
  }
  return board;
}

function roster() {
  const list = el("ul", "roster");
  room.players.forEach((p, i) => {
    const lineup = Object.entries(room.pieces).filter(([, v]) => v.seat === i)
      .map(([c, v]) => c + " · " + (v.pos === 30 ? "已冲线" : v.pos === 0 ? "起点" : "第 " + v.pos + " 格") + (v.trip ? "（绊倒）" : ""));
    list.append(add(el("li"), dot(i), el("strong", "", p.name),
      el("small", "sub", (i === room.seat ? " · 你" : "") + (p.bot ? " · 电脑" : "") + (i === 0 ? " · 房主" : "")),
      el("div", "sub", lineup.join(" / ") || p.hand.join(" / "))));
  });
  return list;
}

function scoreboard() {
  const table = el("table");
  const headings = ["玩家", "R1", "R2", "R3", "R4", "总分", "平均名次"];
  table.append(add(el("thead"), add(el("tr"), ...headings.map(n => el("th", "", n)))));
  const body = el("tbody");
  room.standings.forEach(([i, rank]) => {
    const p = room.players[i],
      total = p.scores.reduce((a, b) => a + b, 0);
    const row = el("tr");
    row.append(add(el("td"), dot(i), document.createTextNode((room.phase === "done" ? "#" + rank + " " : "") + p.name)));
    p.scores.forEach((n, j) => row.append(el("td", "", j < room.round ? String(n) : "—")));
    row.append(el("td", "", String(total)), el("td", "", p.ranks.length ? (p.ranks.reduce((a, b) => a + b, 0) / p.ranks.length).toFixed(2) : "—"));
    body.append(row);
  });
  table.append(body);
  return add(el("div", "table-wrap"), table);
}

function actions() {
  const box = el("section", "panel actionbox");
  const q = room.prompt;
  if (!q) return box;
  const mine = q.seat === room.seat;
  box.append(el("p", "eyebrow", mine ? "轮到你了" : "等待 " + room.players[q.seat].name), el("h2", "", q.title));
  if (room.dice.length) {
    const dice = el("div", "dicebox");
    room.dice.forEach(n => dice.append(el("span", "d6", n)));
    box.append(dice);
  }
  if (mine) {
    const chooseCard = q.kind === "draft" || q.kind === "lineup";
    const group = el("div", chooseCard ? "card-grid" : "row");
    for (const o of q.choices) {
      let b;
      if (chooseCard) {
        b = card(o.value, () => act("choose", o.value));
        b.disabled = busy;
        b.append(el("small", "", cards[o.value][1]));
      } else b = actButton(o.label, "choose", o.value, "primary choice");
      group.append(b);
    }
    box.append(group);
  }
  return box;
}

function draw() {
  if (!room) return;
  const r = room;
  const name = {
    lobby: "候场室",
    draft: "角色选拔",
    lineup: "出场名单",
    race: "赛道现场",
    break: "本轮成绩",
    done: "最终排名"
  } [r.phase];
  const head = add(el("section", "row between racehead"),
    add(el("div"), el("p", "eyebrow roomcode", "房间 " + r.code + " · " + r.board), el("h1", "", name)),
    el("span", "tag", r.round ? "第 " + r.round + " / 4 轮" : r.players.length + " / 8 人"));
  const nodes = [head];
  if (r.phase === "lobby") {
    const panel = add(el("section", "panel"), el("h2", "", "参赛玩家"), roster());
    const controls = el("div", "row");
    if (r.seat === 0) {
      controls.append(actButton("添加电脑", "bot"), actButton("开始比赛", "start", "", "primary"));
      if (r.players.at(-1).bot) controls.append(actButton("移除末位电脑", "remove_bot", "", "plain"));
    } else controls.append(el("p", "sub", "等待房主开始比赛。"));
    const detail = add(el("section", "panel stack"), el("h2", "", "开赛准备"), el("p", "", "将房间码 " + r.code + " 发给其他玩家，或添加电脑开始练习。"),
      el("p", "sub", "当前角色池 " + Object.keys(cards).length + " 名。两人局需 4 名角色，三人局需 6 名。"), controls);
    nodes.push(add(el("div", "twocol"), panel, detail));
  } else {
    if (Object.keys(r.pieces).length) nodes.push(raceBoard());
    if (r.history.length && ["break", "done"].includes(r.phase)) {
      const last = r.history.at(-1);
      nodes.push(add(el("section", "panel"), el("h2", "", "第 " + last.round + " 轮领奖台"),
        el("p", "", "金奖杯 · " + last.podium[0] + "　 /　 银奖杯 · " + last.podium[1])));
    }
    if (r.prompt) nodes.push(actions());
    nodes.push(add(el("div", "twocol"), add(el("section", "panel"), el("h2", "", "实时积分"), scoreboard()),
      add(el("section", "panel"), el("h2", "", "场上队伍"), roster(), el("p", "sub", r.copy ? "模仿猫当前复制 · " + r.copy : ""))));
    nodes.push(add(el("section", "panel section"), el("h2", "", "比赛记录"),
      add(el("ol", "log"), ...r.log.slice().reverse().map(l => el("li", "", l)))));
  }
  nodes.push(add(el("div", "section"), btn("返回大厅", () => leave(r.phase === "done"), "plain")));
  main.replaceChildren(...nodes);
}
(async () => {
  try {
    const res = await fetch("/api/cards");
    cards = await res.json();
    const stored = savedSeat();
    if (stored && stored.code && stored.token) enter(stored);
    else home();
  } catch {
    main.replaceChildren(add(el("section", "panel section"), el("h2", "", "无法加载比赛"), btn("重新连接", () => location.reload())));
  }
})();
