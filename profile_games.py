"""Issue-driven profile games. Python standard library only; no external services."""
import copy
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

START = '<!-- PROFILE-GAMES:START -->'
END = '<!-- PROFILE-GAMES:END -->'
CLASSES = {'warrior': ('⚔️ 战士', 1), 'cleric': ('💚 牧师', 1),
           'rogue': ('🗡️ 盗贼', 3), 'wizard': ('🧙 法师', -1)}
COMMAND = re.compile(r'\[game\] (?:dice:(warrior|cleric|rogue|wizard)|c4:(\d+):(\d+):([1-7]|bot|new))')


def new_board(game_id=1):
    return {'id': game_id, 'ply': 0, 'board': [[0] * 7 for _ in range(6)],
            'turn': 1, 'result': 0, 'recent': []}


def initial():
    return {'c4': new_board(), 'dice': {'counts': dict.fromkeys(CLASSES, 0),
            'recent': [], 'histogram': {}}, 'processed': {}, 'notice': ''}


def winner(board):
    for row in range(6):
        for col in range(7):
            color = board[row][col]
            if not color:
                continue
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                if all(0 <= row + i * dr < 6 and 0 <= col + i * dc < 7
                       and board[row + i * dr][col + i * dc] == color for i in range(4)):
                    return color
    return 3 if all(board[0]) else 0


def drop(board, col, color):
    for row in range(5, -1, -1):
        if board[row][col] == 0:
            board[row][col] = color
            return
    raise ValueError('这一列已满，请刷新主页后选择其他列。')


def bot_column(game):
    legal = [c for c in (3, 2, 4, 1, 5, 0, 6) if not game['board'][0][c]]
    for color in (game['turn'], 3 - game['turn']):
        for col in legal:
            board = copy.deepcopy(game['board'])
            drop(board, col, color)
            if winner(board) == color:
                return col
    return legal[0]


def play(state, title, user, issue_id, roll=None):
    match = COMMAND.fullmatch(title)
    if not match:
        return False
    key = str(issue_id)
    if key in state['processed']:
        return True
    # GitHub login characters only; never render arbitrary issue text as Markdown.
    user = user if re.fullmatch(r'[A-Za-z0-9-]{1,39}', user) else 'visitor'
    profession, game_id, ply, action = match.groups()
    try:
        if profession:
            die = secrets.randbelow(20) + 1 if roll is None else roll
            if not 1 <= die <= 20:
                raise ValueError('骰子必须为 1–20。')
            name, modifier = CLASSES[profession]
            total = die + modifier
            dice = state['dice']
            dice['counts'][profession] += 1
            dice['histogram'][str(total)] = dice['histogram'].get(str(total), 0) + 1
            result = f'@{user} · {name} · D20 **{die}** {modifier:+d} = **{total}**'
            dice['recent'] = [result] + dice['recent'][:9]
        else:
            game = state['c4']
            if (int(game_id), int(ply)) != (game['id'], game['ply']):
                raise ValueError('棋盘已更新，这次旧链接没有落子；请刷新主页再选择。')
            if action == 'new':
                if not game['result']:
                    raise ValueError('当前棋局还没结束，请继续落子。')
                state['c4'] = new_board(game['id'] + 1)
                result = f'@{user} 开始了新一局四子棋。'
            else:
                if game['result']:
                    raise ValueError('本局已经结束，请刷新主页并开始新一局。')
                col = bot_column(game) if action == 'bot' else int(action) - 1
                color = game['turn']
                drop(game['board'], col, color)
                game['ply'] += 1
                game['result'] = winner(game['board'])
                game['turn'] = 3 - color
                who = f'🤖（由 @{user} 请求）' if action == 'bot' else f'@{user}'
                result = f'{who} · {"🔴" if color == 1 else "🔵"} 第 {col + 1} 列'
                game['recent'] = [result] + game['recent'][:7]
        state['notice'] = result
    except ValueError as error:
        result = str(error)
        state['notice'] = f'@{user}：{result}'
    state['processed'][key] = result
    return True


def render(state, repo):
    def link(label, command):
        query = urlencode({'title': '[game] ' + command,
                           'body': '🎮 点击 Create 提交游戏操作，无需修改标题。结果会自动更新到主页，本 Issue 会自动关闭。若棋盘已过期，请刷新主页重新选择。'})
        return f'[{label}](https://github.com/{repo}/issues/new?{query})'

    game = state['c4']
    prefix = f'c4:{game["id"]}:{game["ply"]}:'
    lines = [START, '', '## 🎮 Game Mode', '',
             '> 登录 GitHub → 点击下面的游戏按钮 → 点击 **Create** 提交 → 等自动处理完成后刷新主页。',
             '> 棋盘由所有访客共享，红蓝轮流落子；操作会生成一条自动关闭的 Issue。', '',
             '### 🔴🔵 四子棋 · Connect Four', '',
             f'第 **{game["id"]}** 局 · 已落 **{game["ply"]}** 子', '']
    if game['result']:
        lines += [{1: '🏆 🔴 红方获胜！', 2: '🏆 🔵 蓝方获胜！', 3: '🤝 本局平局。'}[game['result']], '']
    else:
        lines += [f'当前轮到 **{"🔴 红方" if game["turn"] == 1 else "🔵 蓝方"}**。横、竖或斜向连成四子即获胜。', '']
    lines += ['| ' + ' | '.join(str(i) for i in range(1, 8)) + ' |',
              '| ' + ' | '.join([':---:'] * 7) + ' |']
    for row in game['board']:
        lines.append('| ' + ' | '.join(['⚪', '🔴', '🔵'][cell] for cell in row) + ' |')
    lines += ['| ' + ' | '.join(link('⬇️ 落子', prefix + str(i + 1))
               if not game['result'] and not game['board'][0][i] else '—' for i in range(7)) + ' |', '']
    lines += [link('🔄 开始新一局', prefix + 'new') if game['result'] else link('🤖 让机器人代走一步', prefix + 'bot'), '']
    if game['recent']:
        lines += ['<details><summary>最近落子</summary>', ''] + ['- ' + item for item in game['recent']] + ['', '</details>', '']
    lines += ['### 🎲 职业掷骰子 · Roll a D20', '',
              '选择职业，掷一枚 20 面骰（1–20）；最终点数 = 骰子点数 + 职业修正。', '',
              '| 职业 | 修正 | 掷骰次数 | 开始 |', '| :--- | :---: | :---: | :---: |']
    for key, (name, modifier) in CLASSES.items():
        lines.append(f'| {name} | {modifier:+d} | {state["dice"]["counts"][key]} | {link("🎲 掷骰子", "dice:" + key)} |')
    lines += ['', '**最近的冒险者**', '']
    lines += ['- ' + item for item in state['dice']['recent']] or ['等待第一位冒险者……']
    if state['notice']:
        lines += ['', '**最近处理：** ' + state['notice']]
    lines += ['', '<sub>灵感来自 [JonathanGin52 的四子棋](https://github.com/JonathanGin52/JonathanGin52) 和 [benjaminsampica 的职业骰子](https://github.com/benjaminsampica/benjaminsampica)。本仓库独立实现。</sub>', '', END]
    return '\n'.join(lines)


def update_readme(text, block):
    if START not in text and END not in text:
        return text.rstrip() + '\n\n' + block + '\n'
    if text.count(START) != 1 or text.count(END) != 1 or text.index(END) < text.index(START):
        raise ValueError('Game section markers are invalid; README left unchanged.')
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    return before + block + after


def api(path, data=None):
    request = Request('https://api.github.com/repos/' + os.environ['GITHUB_REPOSITORY'] + path,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                               'Accept': 'application/vnd.github+json',
                               'X-GitHub-Api-Version': '2022-11-28'},
                      method='GET' if data is None else 'PATCH')
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout


def main():
    state_path = Path('profile-games-state.json')
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else initial()
    issues, page = [], 1
    while True:
        batch = api(f'/issues?state=open&sort=created&direction=asc&per_page=100&page={page}')
        issues.extend(i for i in batch if 'pull_request' not in i and COMMAND.fullmatch(i['title']))
        if len(batch) < 100:
            break
        page += 1
    for issue in sorted(issues, key=lambda item: item['number']):
        play(state, issue['title'], issue['user']['login'], issue['number'])
    readme = Path('README.md')
    readme.write_text(update_readme(readme.read_text(encoding='utf-8'), render(state, os.environ['GITHUB_REPOSITORY'])), encoding='utf-8')
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    git('add', 'README.md', 'profile-games-state.json')
    if git('diff', '--cached', '--name-only').strip():
        git('commit', '-m', 'chore: update profile games')
        # Retry benign image-generation commits without losing any remote changes.
        for attempt in range(3):
            git('pull', '--rebase', 'origin', 'main')
            try:
                git('push', 'origin', 'HEAD:main')
                break
            except subprocess.CalledProcessError:
                if attempt == 2:
                    raise
    # Durable state is pushed first: failed requests can be retried without double moves.
    for issue in issues:
        api(f'/issues/{issue["number"]}', {'state': 'closed'})
    print(f'Profile games updated; {len(issues)} game request(s) handled.')


def self_test():
    import unittest

    class Rules(unittest.TestCase):
        def test_wins(self):
            for dr, dc, row, col in [(0, 1, 5, 0), (1, 0, 2, 0), (1, 1, 2, 0), (1, -1, 2, 3)]:
                b = new_board()['board']
                for i in range(4):
                    b[row+i*dr][col+i*dc] = 2
                self.assertEqual(winner(b), 2)

        def test_gravity_full_column(self):
            b = new_board()['board']
            for i in range(6):
                drop(b, 0, i % 2 + 1)
            self.assertEqual(b[5][0], 1)
            with self.assertRaises(ValueError):
                drop(b, 0, 1)

        def test_stale_and_duplicate(self):
            s = initial()
            play(s, '[game] c4:1:0:4', 'tester', 1)
            play(s, '[game] c4:1:0:4', 'tester', 1)
            play(s, '[game] c4:1:0:3', 'tester', 2)
            self.assertEqual(s['c4']['ply'], 1)
            self.assertIn('棋盘已更新', s['notice'])
            self.assertFalse(play(s, '[game] dice:$(bad)', 'tester', 3))

        def test_win_and_reset(self):
            s = initial()
            for n, col in enumerate([1, 2, 1, 2, 1, 2, 1]):
                play(s, f'[game] c4:1:{n}:{col}', 'tester', n+1)
            self.assertEqual(s['c4']['result'], 1)
            play(s, '[game] c4:1:7:3', 'tester', 8)
            self.assertEqual(s['c4']['ply'], 7)
            play(s, '[game] c4:1:7:new', 'tester', 9)
            self.assertEqual(s['c4']['id'], 2)

        def test_bot(self):
            g = new_board()
            g['board'][5][:3] = [2, 2, 2]
            self.assertEqual(bot_column(g), 3)
            g['board'][5][3] = 1
            g['board'][5][4:] = [1, 1, 0]
            self.assertEqual(bot_column(g), 6)

        def test_dice(self):
            s = initial()
            for i, (key, (_, modifier)) in enumerate(CLASSES.items()):
                for roll in (1, 20):
                    issue = i * 20 + roll
                    play(s, '[game] dice:' + key, 'tester', issue, roll)
                    play(s, '[game] dice:' + key, 'tester', issue, roll)
                    self.assertIn(f'= **{roll+modifier}**', s['dice']['recent'][0])
                self.assertEqual(s['dice']['counts'][key], 2)

        def test_preserve_readme(self):
            block = render(initial(), 'test/test')
            text = 'CSDN and existing profile\n\n' + block + '\nKEEP\n'
            updated = update_readme(text, START + '\nnew\n' + END)
            self.assertTrue(updated.startswith('CSDN and existing profile\n\n'))
            self.assertTrue(updated.endswith('\nKEEP\n'))
            self.assertEqual(updated.count(START), 1)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Rules)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    self_test() if '--self-test' in sys.argv else main()
