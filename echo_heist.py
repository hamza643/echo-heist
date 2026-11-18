#!/usr/bin/env python3
"""
ECHO HEIST  -  a time-loop stealth heist (single file, pygame)

Run:   pip install pygame      then      python echo_heist.py

Har loop mein tum vault loot karke exit tak wapas aate ho. Guards tumhari PICHLI
saari attempts yaad rakhte hain:
  * Path-frequency table: kis lane (LEFT / MIDDLE / RIGHT) se kitni baar gaye.
    Jis lane mein count >= 2 ho, wahan agli loop mein ambush guard pehle se khara hota hai.
  * Heat-map (tile visit frequency): "Tracker" guard tumhare sabse zyada use kiye hue
    tiles par patrol karta hai.
  * Tumhara purana run ek ECHO (ghost) ban kar replay hota hai - guards ghost ko dekh kar
    distract ho jate hain, aur agar ghost unhe touch kare to woh stun ho jate hain.

Controls
  WASD / Arrows : move          SHIFT : sneak (slow, quiet, harder to spot)
  SPACE / ENTER : continue      H : heat-map     P / ESC : pause
  M : mute      F : fullscreen  R : memory wipe (new game)
"""
import math
import random
import sys
import array
from collections import deque

import pygame

# ----------------------------------------------------------------------------
W, H = 1280, 720
TS = 32
GW, GH = 40, 20
OY = 80
FPS = 60
DT = 1.0 / FPS
LOOP_TIME = 60.0
LANES = ["LEFT", "MIDDLE", "RIGHT"]

START_POS = (20 * TS, 18 * TS)
VAULT_POS = (20 * TS, 2 * TS)
PAD_RECT = pygame.Rect(18 * TS, 17 * TS, 4 * TS, 2 * TS)
VAULT_RECT = pygame.Rect(19 * TS, 1 * TS, 2 * TS, 2 * TS)

FONT_NAMES = "consolas,dejavusansmono,menlo,couriernew,monospace"


def clamp(v, a, b):
    return max(a, min(b, v))


def lerp(a, b, t):
    return a + (b - a) * t


def ang_diff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def tile_of(x, y):
    return int(x // TS), int(y // TS)


def center(t):
    return (t[0] * TS + TS / 2, t[1] * TS + TS / 2)


def lerp_col(c1, c2, t):
    return tuple(int(lerp(c1[i], c2[i], t)) for i in range(3))


# ----------------------------------------------------------------------------
# Cached glow / light sprites
_glow, _light = {}, {}


def glow(radius, color, intensity=1.0):
    k = (radius, color, int(intensity * 10))
    s = _glow.get(k)
    if s is None:
        s = pygame.Surface((radius * 2, radius * 2))
        s.fill((0, 0, 0))
        for r in range(radius, 0, -2):
            t = (1 - r / radius) ** 2 * intensity
            c = (int(color[0] * t), int(color[1] * t), int(color[2] * t))
            pygame.draw.circle(s, c, (radius, radius), r)
        _glow[k] = s
    return s


def light(radius, strength):
    k = (radius, strength)
    s = _light.get(k)
    if s is None:
        s = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
        for r in range(radius, 0, -3):
            a = int(strength * (1 - r / radius) ** 1.5)
            pygame.draw.circle(s, (0, 0, 0, a), (radius, radius), r)
        _light[k] = s
    return s


def add_glow(surf, x, y, r, color, inten=1.0):
    surf.blit(glow(r, color, inten), (x - r, y - r), special_flags=pygame.BLEND_ADD)


def font(sz, bold=False):
    return pygame.font.SysFont(FONT_NAMES, sz, bold=bold)


def draw_text(surf, txt, f, col, pos, anchor="l", shadow=True, alpha=255):
    img = f.render(txt, True, col)
    if alpha < 255:
        img.set_alpha(alpha)
    r = img.get_rect()
    if anchor == "l":
        r.topleft = pos
    elif anchor == "c":
        r.midtop = pos
    elif anchor == "r":
        r.topright = pos
    else:
        r.center = pos
    if shadow:
        sh = f.render(txt, True, (0, 0, 0))
        sh.set_alpha(min(alpha, 170))
        surf.blit(sh, (r.x + 2, r.y + 2))
    surf.blit(img, r)
    return r


def panel(surf, rect, color=(10, 14, 28), alpha=215, border=(70, 120, 200)):
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, (*color, alpha), s.get_rect(), border_radius=10)
    pygame.draw.rect(s, (*border, 255), s.get_rect(), 2, border_radius=10)
    surf.blit(s, rect.topleft)


# ----------------------------------------------------------------------------
# Sound (synthesised, no assets)
def synth(f0, f1, dur, vol=0.25, wave="sine"):
    chans = pygame.mixer.get_init()[2]
    n = int(44100 * dur)
    buf = array.array("h")
    ph = 0.0
    for i in range(n):
        t = i / n
        ph += (f0 + (f1 - f0) * t) / 44100.0
        if wave == "sine":
            v = math.sin(2 * math.pi * ph)
        elif wave == "sq":
            v = 1.0 if (ph % 1) < 0.5 else -1.0
        else:
            v = 2 * (ph % 1) - 1
        env = min(1.0, t * 25) * (1 - t) ** 1.3
        sample = int(v * env * vol * 32767)
        for _ in range(chans):
            buf.append(sample)
    return pygame.mixer.Sound(buffer=buf)


class Sfx:
    def __init__(self):
        self.on = True
        self.s = {}
        try:
            self.s = {
                "alert": synth(950, 520, 0.25, 0.16, "sq"),
                "loot": synth(500, 1300, 0.4, 0.25),
                "caught": synth(260, 50, 0.7, 0.3, "saw"),
                "rewind": synth(1400, 120, 0.9, 0.18, "saw"),
                "win": synth(520, 1040, 0.6, 0.25),
                "lure": synth(300, 750, 0.18, 0.2),
                "stun": synth(500, 90, 0.3, 0.22, "sq"),
                "cam": synth(1200, 1200, 0.3, 0.12, "sq"),
                "start": synth(300, 600, 0.25, 0.2),
            }
        except Exception:
            self.s = {}

    def play(self, name):
        if self.on and name in self.s:
            self.s[name].play()


# ----------------------------------------------------------------------------
class World:
    def __init__(self):
        g = [[1] * GW for _ in range(GH)]

        def carve(x0, y0, x1, y1):
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    g[y][x] = 0

        carve(1, 1, 38, 3)      # top hall (vault)
        carve(1, 15, 38, 18)    # bottom hall (street / exit)
        carve(3, 4, 6, 14)      # left lane
        carve(18, 4, 21, 14)    # middle lane
        carve(33, 4, 36, 14)    # right lane
        carve(7, 9, 17, 9)      # left <-> middle connector
        carve(22, 9, 32, 9)     # middle <-> right connector
        for (x, y) in [(4, 7), (5, 11), (19, 6), (20, 12), (34, 8), (35, 12),
                       (10, 2), (29, 2), (10, 16), (29, 16), (15, 3), (24, 3)]:
            g[y][x] = 1
        self.g = g

    def solid(self, tx, ty):
        return tx < 0 or ty < 0 or tx >= GW or ty >= GH or self.g[ty][tx] == 1

    def solid_px(self, x, y):
        return self.solid(int(x // TS), int(y // TS))

    def los(self, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = int(math.hypot(dx, dy) / 6) + 1
        for i in range(1, n):
            t = i / n
            if self.solid_px(a[0] + dx * t, a[1] + dy * t):
                return False
        return True

    def cast(self, x, y, ang, maxd):
        cx, cy = math.cos(ang), math.sin(ang)
        d = 0.0
        while d < maxd:
            d += 6
            if self.solid_px(x + cx * d, y + cy * d):
                return max(0.0, d - 4)
        return maxd

    def bfs(self, a, b):
        if a == b or self.solid(*b):
            return []
        prev = {a: None}
        q = deque([a])
        while q:
            c = q.popleft()
            if c == b:
                break
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + dx, c[1] + dy)
                if n not in prev and not self.solid(*n):
                    prev[n] = c
                    q.append(n)
        if b not in prev:
            return []
        path, c = [], b
        while c != a:
            path.append(c)
            c = prev[c]
        path.reverse()
        return path


def build_static(world):
    s = pygame.Surface((GW * TS, GH * TS))
    rnd = random.Random(11)
    g = world.g
    for ty in range(GH):
        for tx in range(GW):
            r = pygame.Rect(tx * TS, ty * TS, TS, TS)
            if g[ty][tx] == 0:
                base = (29, 34, 49) if (tx + ty) % 2 == 0 else (33, 39, 57)
                pygame.draw.rect(s, base, r)
                for _ in range(4):
                    s.set_at((r.x + rnd.randrange(TS), r.y + rnd.randrange(TS)), (48, 57, 80))
                pygame.draw.rect(s, (24, 28, 42), r, 1)
            else:
                pygame.draw.rect(s, (14, 16, 26), r)
                off = 16 if ty % 2 else 0
                pygame.draw.line(s, (22, 26, 40), (r.x, r.y + 16), (r.right, r.y + 16))
                pygame.draw.line(s, (22, 26, 40), (r.x + off, r.y), (r.x + off, r.y + 16))
                pygame.draw.line(s, (22, 26, 40), (r.x + 16 - off, r.y + 16), (r.x + 16 - off, r.bottom))
                if ty + 1 < GH and g[ty + 1][tx] == 0:
                    pygame.draw.rect(s, (38, 45, 72), (r.x, r.bottom - 10, TS, 10))
                    pygame.draw.line(s, (90, 125, 200), (r.x, r.bottom - 10), (r.right, r.bottom - 10), 2)
                if ty > 0 and g[ty - 1][tx] == 0:
                    pygame.draw.line(s, (60, 90, 150), (r.x, r.y), (r.right, r.y), 2)
                if tx > 0 and g[ty][tx - 1] == 0:
                    pygame.draw.line(s, (50, 75, 125), (r.x, r.y), (r.x, r.bottom), 2)
                if tx + 1 < GW and g[ty][tx + 1] == 0:
                    pygame.draw.line(s, (50, 75, 125), (r.right - 1, r.y), (r.right - 1, r.bottom), 2)
    # vault floor
    s.set_clip(VAULT_RECT.inflate(32, 0))
    for ty in range(1, 3):
        for tx in range(18, 22):
            c = (56, 44, 16) if (tx + ty) % 2 else (46, 36, 12)
            pygame.draw.rect(s, c, (tx * TS, ty * TS, TS, TS))
            pygame.draw.rect(s, (90, 70, 24), (tx * TS, ty * TS, TS, TS), 1)
    s.set_clip(None)
    # exit pad hazard stripes
    s.set_clip(PAD_RECT)
    pygame.draw.rect(s, (14, 44, 32), PAD_RECT)
    for k in range(-PAD_RECT.h, PAD_RECT.w, 22):
        pygame.draw.line(s, (28, 120, 70), (PAD_RECT.x + k, PAD_RECT.bottom),
                         (PAD_RECT.x + k + PAD_RECT.h, PAD_RECT.y), 5)
    s.set_clip(None)
    pygame.draw.rect(s, (60, 220, 130), PAD_RECT, 2)
    return s


def make_vignette():
    s = pygame.Surface((GW * TS, GH * TS), pygame.SRCALPHA)
    w, h = s.get_size()
    for i in range(48):
        a = int(140 * (1 - i / 48) ** 2.2)
        pygame.draw.rect(s, (0, 0, 0, a), (i * 3, i * 3, w - i * 6, h - i * 6), 3)
    return s


def make_scanlines():
    s = pygame.Surface((GW * TS, GH * TS), pygame.SRCALPHA)
    for y in range(0, GH * TS, 3):
        pygame.draw.line(s, (0, 0, 0, 30), (0, y), (GW * TS, y))
    return s


# ----------------------------------------------------------------------------
class Particles:
    def __init__(self):
        self.p = []

    def burst(self, x, y, col, n=24, speed=150, life=0.7, size=3):
        for _ in range(n):
            a = random.random() * math.tau
            v = random.random() * speed
            lf = life * (0.5 + random.random() * 0.8)
            self.p.append([x, y, math.cos(a) * v, math.sin(a) * v, lf, lf, col,
                           size * (0.5 + random.random())])

    def update(self, dt):
        for q in self.p:
            q[0] += q[2] * dt
            q[1] += q[3] * dt
            q[2] *= 0.96
            q[3] *= 0.96
            q[4] -= dt
        self.p = [q for q in self.p if q[4] > 0]

    def draw(self, surf):
        for q in self.p:
            a = int(255 * q[4] / q[5])
            pygame.draw.circle(surf, (*q[6], a), (int(q[0]), int(q[1])), max(1, int(q[7])))


# ----------------------------------------------------------------------------
class Player:
    def __init__(self):
        self.x, self.y = START_POS
        self.sneak = False
        self.moving = False
        self.ang = -math.pi / 2
        self.trail = deque(maxlen=14)

    def blocked(self, W_, x, y, hw=7):
        return (W_.solid_px(x - hw, y - hw) or W_.solid_px(x + hw, y - hw) or
                W_.solid_px(x - hw, y + hw) or W_.solid_px(x + hw, y + hw))

    def update(self, W_, keys, dt, looted):
        dx = int(bool(keys[pygame.K_d] or keys[pygame.K_RIGHT])) - int(bool(keys[pygame.K_a] or keys[pygame.K_LEFT]))
        dy = int(bool(keys[pygame.K_s] or keys[pygame.K_DOWN])) - int(bool(keys[pygame.K_w] or keys[pygame.K_UP]))
        self.sneak = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT])
        self.moving = bool(dx or dy)
        if self.moving:
            n = math.hypot(dx, dy)
            dx, dy = dx / n, dy / n
            self.ang = math.atan2(dy, dx)
        sp = (70 if self.sneak else 150) * (0.95 if looted else 1.0)
        nx = self.x + dx * sp * dt
        if not self.blocked(W_, nx, self.y):
            self.x = nx
        ny = self.y + dy * sp * dt
        if not self.blocked(W_, self.x, ny):
            self.y = ny


# ----------------------------------------------------------------------------
class Guard:
    COL = {"patrol": (255, 205, 90), "ambush": (255, 95, 120), "tracker": (255, 140, 50)}

    def __init__(self, kind, tile, wps=None, face=0.0, power=1, loop=1):
        self.kind = kind
        self.x, self.y = center(tile)
        self.home = tile
        self.wp = wps or []
        self.wi = 1 if len(self.wp) > 1 else 0
        self.home_state = "ambush" if kind == "ambush" else "patrol"
        self.state = self.home_state
        self.ang = self.home_ang = self.want = self.sbase = face
        self.path = []
        self.meter = 0.0
        self.timer = 0.0
        self.stun = 0.0
        self.imm = 0.0
        self.repath = 0.0
        self.pause = 0.0
        self.phase = random.random() * math.tau
        self.last = (self.x, self.y)
        self.target = (self.x, self.y)
        self.poly = []
        if kind == "ambush":
            self.range = min(270, 150 + 30 * power)
            self.fov = math.radians(58 + 4 * min(power, 5))
            self.speed = 78
        elif kind == "tracker":
            self.range, self.fov, self.speed = 205, math.radians(76), 90
        else:
            self.range, self.fov, self.speed = 165, math.radians(70), 72
        self.chase_speed = 116 + 2.5 * min(loop, 10)

    # -- helpers
    def goto(self, W_, px, py):
        self.path = W_.bfs(tile_of(self.x, self.y), tile_of(px, py))

    def step(self, dt, speed):
        if not self.path:
            return False
        tx, ty = center(self.path[0])
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        mv = speed * dt
        if d <= mv:
            self.x, self.y = tx, ty
            self.path.pop(0)
        else:
            self.x += dx / d * mv
            self.y += dy / d * mv
            self.want = math.atan2(dy, dx)
        return True

    def investigate(self, G, pos):
        self.state = "search"
        self.target = pos
        self.goto(G.world, *pos)
        self.timer = 3.0
        self.sbase = self.ang

    def compute_poly(self, W_):
        n = 20
        pts = [(self.x, self.y)]
        for i in range(n + 1):
            a = self.ang - self.fov / 2 + self.fov * i / n
            d = W_.cast(self.x, self.y, a, self.range)
            pts.append((self.x + math.cos(a) * d, self.y + math.sin(a) * d))
        self.poly = pts

    # -- brain
    def update(self, G, dt):
        W_, p = G.world, G.player
        if self.stun > 0:
            self.stun -= dt
            self.compute_poly(W_)
            return
        self.imm = max(0.0, self.imm - dt)
        rng = self.range * (0.75 if p.sneak else 1.0)
        seen, d = G.can_see(self.x, self.y, self.ang, self.fov, rng, p.x, p.y, 34)
        if seen:
            rate = (0.9 + 1.3 * (1 - d / max(rng, 1))) * (0.7 if p.sneak else 1.0)
            self.meter = min(1.0, self.meter + rate * dt)
            self.last = (p.x, p.y)
        elif p.moving and not p.sneak and d < 95:      # footsteps
            self.meter = min(0.99, self.meter + 0.5 * dt)
            self.last = (p.x, p.y)
            if self.meter > 0.4 and self.state in ("patrol", "ambush", "return"):
                self.investigate(G, self.last)
        else:
            self.meter = max(0.0, self.meter - 0.45 * dt)

        if self.meter >= 1.0 and self.state != "chase":
            self.state = "chase"
            self.timer = 4.0
            self.path = []
            self.repath = 0
            G.on_spotted(self)

        # ghost (echo) lure
        gseen = False
        if self.state != "chase":
            for gx, gy, gi in G.ghost_now:
                ok, gd = G.can_see(self.x, self.y, self.ang, self.fov, self.range, gx, gy, 20)
                if ok and self.imm <= 0:
                    gseen = True
                    if self.state != "distract":
                        G.on_lure(self)
                    self.state = "distract"
                    self.timer = 2.6
                    self.target = (gx, gy)
                    break

        moving = False
        sp = self.speed * (1.12 if G.looted else 1.0)
        st = self.state
        if st == "patrol":
            if self.pause > 0:
                self.pause -= dt
            elif not self.path:
                t = tile_of(self.x, self.y)
                w = self.wp[self.wi]
                if t == w:
                    self.wi = (self.wi + 1) % len(self.wp)
                    self.pause = 0.6
                else:
                    self.goto(W_, *center(w))
            moving = self.step(dt, sp)
        elif st == "distract":
            self.repath -= dt
            if self.repath <= 0:
                self.goto(W_, *self.target)
                self.repath = 0.35
            moving = self.step(dt, sp * 1.15)
            for gx, gy, gi in G.ghost_now:
                if math.hypot(gx - self.x, gy - self.y) < 24:
                    G.stun_guard(self, gx, gy)
                    break
            if not gseen:
                self.timer -= dt
                if self.timer <= 0:
                    self.state = "return"
                    self.path = []
        elif st == "chase":
            if seen:
                self.timer = 4.0
            else:
                self.timer -= dt
            self.repath -= dt
            if self.repath <= 0:
                self.goto(W_, p.x, p.y)
                self.repath = 0.25
            if self.path:
                moving = self.step(dt, self.chase_speed)
            else:
                dx, dy = p.x - self.x, p.y - self.y
                dd = math.hypot(dx, dy) or 1
                self.x += dx / dd * self.chase_speed * dt
                self.y += dy / dd * self.chase_speed * dt
                self.want = math.atan2(dy, dx)
                moving = True
            if self.timer <= 0:
                self.investigate(G, self.last)
                self.meter = 0.3
        elif st == "search":
            if self.path:
                moving = self.step(dt, sp * 1.1)
                self.sbase = self.ang
            else:
                self.timer -= dt
                if self.timer <= 0:
                    self.state = "return"
        elif st == "return":
            if not self.path:
                if tile_of(self.x, self.y) == self.home:
                    self.state = self.home_state
                    self.pause = 0.3
                else:
                    self.goto(W_, *center(self.home))
            moving = self.step(dt, sp)

        # facing
        if moving:
            want = self.want
        elif self.state == "ambush":
            want = self.home_ang + 0.65 * math.sin(G.t * 0.9 + self.phase)
        elif self.state == "search":
            want = self.sbase + 1.2 * math.sin(self.timer * 2.4)
        else:
            want = self.ang
        tr = (7 if self.state == "chase" else 4.5) * dt
        self.ang += clamp(ang_diff(want, self.ang), -tr, tr)
        self.compute_poly(W_)


class Camera:
    def __init__(self, x, y, base, swing, rng=190, fov=0.7, speed=1.1, phase=0.0):
        self.x, self.y, self.base, self.swing = x, y, base, swing
        self.range, self.fov, self.speed, self.phase = rng, fov, speed, phase
        self.ang = base
        self.meter = 0.0
        self.cool = 0.0
        self.poly = []

    def update(self, G, dt):
        self.ang = self.base + self.swing * math.sin(G.t * self.speed + self.phase)
        p = G.player
        rng = self.range * (0.8 if p.sneak else 1.0)
        seen, d = G.can_see(self.x, self.y, self.ang, self.fov, rng, p.x, p.y, 0)
        self.cool = max(0.0, self.cool - dt)
        if seen and self.cool <= 0:
            self.meter += 1.3 * dt
        else:
            self.meter = max(0.0, self.meter - 0.6 * dt)
        if self.meter >= 1.0:
            self.meter = 0.0
            self.cool = 4.0
            G.camera_alarm(self)
        pts = [(self.x, self.y)]
        n = 14
        for i in range(n + 1):
            a = self.ang - self.fov / 2 + self.fov * i / n
            dd = G.world.cast(self.x, self.y, a, self.range)
            pts.append((self.x + math.cos(a) * dd, self.y + math.sin(a) * dd))
        self.poly = pts


# ----------------------------------------------------------------------------
class Game:
    def __init__(self, screen):
        self.screen = screen
        self.world = World()
        self.static = build_static(self.world).convert()
        self.view = pygame.Surface((GW * TS, GH * TS)).convert()
        self.dark = pygame.Surface((GW * TS, GH * TS), pygame.SRCALPHA)
        self.fx = pygame.Surface((GW * TS, GH * TS), pygame.SRCALPHA)
        self.flash = pygame.Surface((GW * TS, GH * TS), pygame.SRCALPHA)
        self.vig = make_vignette()
        self.scanl = make_scanlines()
        self.f_s, self.f_m = font(14), font(18, True)
        self.f_l, self.f_xl, self.f_xxl = font(30, True), font(48, True), font(92, True)
        self.sfx = Sfx()
        self.particles = Particles()
        self.t = 0.0
        self.st = 0.0
        self.state = "title"
        self.show_heat = False
        self.shake = 0.0
        self.alarm_t = 0.0
        self.toasts = []
        self.best = 0
        self.bg_title = pygame.Surface((W, H))
        for y in range(H):
            self.bg_title.fill(lerp_col((6, 8, 20), (22, 10, 44), y / H), (0, y, W, 1))
        self.new_game()

    # ---------------------------------------------------------------- state
    def set_state(self, s):
        self.state = s
        self.st = 0.0

    def new_game(self):
        self.loop = 0
        self.score = 0
        self.banked = 0
        self.lane_counts = [0, 0, 0]
        self.lane_hist = []
        self.history = []          # [(loop_no, trail)]
        self.ghosts = []
        self.heat = [[0.0] * GW for _ in range(GH)]
        self.guards, self.cams, self.ghost_now = [], [], []
        self.deployed, self.tracker = [], False
        self.player = Player()
        self.looted = False
        self.frame = 0
        self.t_left = LOOP_TIME
        self.recording = []
        self.lane_frames = [0, 0, 0]
        self.lures = 0
        self.result = None
        self.result_info = []

    def predicted(self):
        if sum(self.lane_counts) == 0:
            return None
        best, bi = -1, None
        for i in list(range(3)):
            c = self.lane_counts[i]
            rec = max([k for k, l in enumerate(self.lane_hist) if l == i], default=-1)
            key = (c, rec)
            if bi is None or key > best:
                best, bi = key, i
        return bi

    def start_loop(self):
        self.loop += 1
        self.player = Player()
        self.t_left = LOOP_TIME
        self.frame = 0
        self.recording = []
        self.lane_frames = [0, 0, 0]
        self.looted = False
        self.lures = 0
        self.alarm_t = 0.0
        self.ghosts = self.history[-2:]
        self.setup_guards()
        self.setup_cams()
        self.compute_ghosts()
        self.particles.p.clear()
        self.toasts.clear()

    def hot_waypoints(self):
        cand = []
        for ty in range(1, 15):
            for tx in range(GW):
                h = self.heat[ty][tx]
                if h > 0.3 and not self.world.solid(tx, ty):
                    cand.append((h, tx, ty))
        cand.sort(reverse=True)
        sel = []
        for h, tx, ty in cand:
            if all(abs(tx - a) + abs(ty - b) >= 7 for a, b in sel):
                sel.append((tx, ty))
            if len(sel) >= 3:
                break
        return sel

    def setup_guards(self):
        L, c = self.loop, self.lane_counts
        gs = [
            Guard("patrol", (2, 2), [(2, 2), (16, 2), (37, 2), (24, 2)], 0.0, loop=L),
            Guard("patrol", (36, 17), [(36, 17), (25, 16), (3, 17), (14, 16)], math.pi, loop=L),
        ]
        posts = [((4, 10), (5, 6)), ((19, 10), (20, 5)), ((35, 10), (34, 5))]
        self.deployed = []
        for i in range(3):
            if c[i] >= 2:
                gs.append(Guard("ambush", posts[i][0], face=math.pi / 2, power=c[i], loop=L))
                self.deployed.append(i)
                if c[i] >= 4:
                    gs.append(Guard("ambush", posts[i][1], face=-math.pi / 2, power=c[i] - 2, loop=L))
        wps = self.hot_waypoints()
        self.tracker = len(self.history) >= 2 and len(wps) >= 2
        if self.tracker:
            gs.append(Guard("tracker", (38, 2), [(38, 2)] + wps, math.pi, loop=L))
        for g in gs:
            g.compute_poly(self.world)
        self.guards = gs

    def setup_cams(self):
        self.cams = [
            Camera(10 * TS + 16, 36, math.pi / 2, 0.75, 200, 0.65, 1.1),
            Camera(29 * TS + 16, 18 * TS + 24, -math.pi / 2, 0.75, 200, 0.65, 0.9, 2.0),
            Camera(20 * TS, 4 * TS + 6, math.pi / 2, 0.55, 175, 0.6, 1.4, 1.0),
        ]

    def compute_ghosts(self):
        gi = max(0, self.frame - 1)
        self.ghost_now = []
        for i, (ln, tr) in enumerate(self.ghosts):
            if gi < len(tr):
                self.ghost_now.append((tr[gi][0], tr[gi][1], i))

    # ---------------------------------------------------------------- events from AI
    def can_see(self, ox, oy, ang, fov, rng, tx, ty, near):
        dx, dy = tx - ox, ty - oy
        d = math.hypot(dx, dy)
        ok = False
        if d <= near:
            ok = True
        elif d <= rng and abs(ang_diff(math.atan2(dy, dx), ang)) <= fov / 2:
            ok = True
        if ok and not self.world.los((ox, oy), (tx, ty)):
            ok = False
        return ok, d

    def toast(self, msg, col=(255, 255, 255)):
        self.toasts.append([msg, col, 2.4])
        self.toasts = self.toasts[-4:]

    def raise_alarm(self, src, pos):
        for g in self.guards:
            if g is not src and g.state != "chase" and g.stun <= 0:
                g.investigate(self, pos)

    def on_spotted(self, g):
        self.sfx.play("alert")
        self.toast("SPOTTED!", (255, 80, 80))
        self.shake = max(self.shake, 0.3)
        self.alarm_t = 1.5
        self.raise_alarm(g, (self.player.x, self.player.y))

    def camera_alarm(self, cam):
        self.sfx.play("cam")
        self.toast("CAMERA ALERT - guards en route", (255, 120, 60))
        self.alarm_t = 2.0
        self.shake = max(self.shake, 0.2)
        self.raise_alarm(None, (self.player.x, self.player.y))

    def on_lure(self, g):
        self.lures += 1
        self.sfx.play("lure")
        self.toast("YOUR ECHO LURED A GUARD", (170, 140, 255))

    def stun_guard(self, g, gx, gy):
        g.stun = 2.2
        g.imm = 4.0
        g.state = "return"
        g.path = []
        g.meter = 0.0
        self.sfx.play("stun")
        self.particles.burst(g.x, g.y, (190, 160, 255), 28, 180, 0.8, 3)
        self.toast("ECHO STUNNED A GUARD", (190, 160, 255))

    # ---------------------------------------------------------------- run end
    def end_run(self, result):
        self.history.append((self.loop, self.recording[:]))
        lane = None
        if sum(self.lane_frames) >= 30:
            lane = max(range(3), key=lambda i: self.lane_frames[i])
            self.lane_counts[lane] += 1
            self.lane_hist.append(lane)
        info = []
        p = self.player
        if result == "escaped":
            gain = 1000 + int(self.t_left * 15) + 100 * self.lures
            self.score += gain
            self.banked += 1
            self.best = max(self.best, self.score)
            info.append("Loot banked: +%d" % gain)
            self.sfx.play("win")
            self.particles.burst(p.x, p.y, (255, 215, 80), 90, 260, 1.4, 4)
        elif result == "caught":
            self.sfx.play("caught")
            self.shake = 0.6
        else:
            self.sfx.play("caught")
        info.append("Route taken: %s" % (LANES[lane] + " lane" if lane is not None else "never reached a lane"))
        if lane is not None:
            info.append("Guards now remember %s x%d" % (LANES[lane], self.lane_counts[lane]))
        info.append("Your echo will replay next loop - use it as a decoy.")
        self.result, self.result_info = result, info
        self.set_state("result")

    # ---------------------------------------------------------------- update
    def update(self, keys):
        self.t += DT
        self.st += DT
        self.shake = max(0.0, self.shake - DT)
        self.alarm_t = max(0.0, self.alarm_t - DT)
        for tt in self.toasts:
            tt[2] -= DT
        self.toasts = [tt for tt in self.toasts if tt[2] > 0]
        if self.state == "play":
            self.update_play(keys)
        elif self.state in ("briefing", "result"):
            self.particles.update(DT)

    def update_play(self, keys):
        self.frame += 1
        self.t_left -= DT
        p = self.player
        p.update(self.world, keys, DT, self.looted)
        self.recording.append((p.x, p.y))
        if self.frame % 2 == 0:
            p.trail.append((p.x, p.y))
        tx, ty = tile_of(p.x, p.y)
        if 0 <= tx < GW and 0 <= ty < GH:
            self.heat[ty][tx] += DT
        if 4 <= ty <= 14:
            self.lane_frames[0 if tx < 12 else (1 if tx < 27 else 2)] += 1

        prev = len(self.ghost_now)
        self.compute_ghosts()
        for i, (ln, tr) in enumerate(self.ghosts):
            if self.frame - 1 == len(tr):
                self.particles.burst(tr[-1][0], tr[-1][1], (160, 130, 255), 24, 90, 0.8)
        for g in self.guards:
            g.update(self, DT)
        for c in self.cams:
            c.update(self, DT)
        self.particles.update(DT)

        if not self.looted and math.hypot(p.x - VAULT_POS[0], p.y - VAULT_POS[1]) < 36:
            self.looted = True
            self.sfx.play("loot")
            self.particles.burst(VAULT_POS[0], VAULT_POS[1], (255, 215, 80), 60, 220, 1.0, 4)
            self.toast("LOOT SECURED - GET TO THE EXIT!", (255, 215, 80))
            self.alarm_t = 1.0
        if self.looted and PAD_RECT.collidepoint(p.x, p.y):
            self.end_run("escaped")
            return
        for g in self.guards:
            if g.stun <= 0 and math.hypot(g.x - p.x, g.y - p.y) < 22:
                self.particles.burst(p.x, p.y, (255, 70, 70), 50, 220, 0.9, 4)
                self.end_run("caught")
                return
        if self.t_left <= 0:
            self.t_left = 0
            self.end_run("time")

    # ---------------------------------------------------------------- input
    def handle_event(self, e):
        if e.type != pygame.KEYDOWN:
            return
        k = e.key
        if k == pygame.K_m:
            self.sfx.on = not self.sfx.on
        elif k == pygame.K_h:
            self.show_heat = not self.show_heat
        elif k == pygame.K_f:
            try:
                pygame.display.toggle_fullscreen()
            except Exception:
                pass
        elif k == pygame.K_r and self.state != "title":
            self.new_game()
            self.begin_briefing()
        elif k in (pygame.K_p, pygame.K_ESCAPE):
            if self.state == "play":
                self.set_state("pause")
            elif self.state == "pause":
                self.state = "play"
            elif self.state == "title" and k == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit()
        elif k in (pygame.K_SPACE, pygame.K_RETURN):
            if self.state == "title":
                self.new_game()
                self.begin_briefing()
            elif self.state == "briefing" and self.st > 0.6:
                self.sfx.play("start")
                self.set_state("play")
            elif self.state == "result" and self.st > 0.8:
                self.begin_briefing()
            elif self.state == "pause":
                self.state = "play"
        elif k == pygame.K_q and self.state == "pause":
            pygame.quit()
            sys.exit()

    def begin_briefing(self):
        self.start_loop()
        self.sfx.play("rewind")
        self.set_state("briefing")

    # ---------------------------------------------------------------- drawing: world
    def draw_vault(self, v):
        cx, cy = VAULT_POS
        pulse = 0.6 + 0.4 * math.sin(self.t * 3)
        if not self.looted:
            add_glow(v, cx, cy, 90, (255, 190, 50), pulse * 0.7)
            pygame.draw.rect(v, (34, 28, 10), (cx - 28, cy - 22, 56, 44), border_radius=6)
            pygame.draw.rect(v, (235, 185, 55), (cx - 28, cy - 22, 56, 44), 3, border_radius=6)
            pygame.draw.circle(v, (235, 185, 55), (cx, cy), 12, 3)
            pygame.draw.line(v, (255, 230, 120), (cx - 8, cy), (cx + 8, cy), 2)
            pygame.draw.line(v, (255, 230, 120), (cx, cy - 8), (cx, cy + 8), 2)
            draw_text(v, "VAULT", self.f_s, (255, 220, 120), (cx, cy + 26), "c")
        else:
            pygame.draw.rect(v, (20, 18, 12), (cx - 28, cy - 22, 56, 44), border_radius=6)
            pygame.draw.rect(v, (90, 75, 30), (cx - 28, cy - 22, 56, 44), 2, border_radius=6)
            draw_text(v, "EMPTY", self.f_s, (140, 120, 70), (cx, cy), "m")

    def draw_exit(self, v):
        pulse = 0.5 + 0.5 * math.sin(self.t * (6 if self.looted else 2.5))
        add_glow(v, PAD_RECT.centerx, PAD_RECT.centery, 120, (40, 230, 120),
                 (0.9 if self.looted else 0.35) * (0.5 + 0.5 * pulse))
        draw_text(v, "EXIT", self.f_m, (120, 255, 170), PAD_RECT.center, "m")

    def draw_heat(self, fx):
        mx = max(max(r) for r in self.heat) or 1.0
        for ty in range(GH):
            for tx in range(GW):
                h = self.heat[ty][tx]
                if h > 0.05:
                    t = min(1.0, math.sqrt(h / mx))
                    col = lerp_col((40, 80, 255), (255, 110, 30), t)
                    pygame.draw.rect(fx, (*col, int(40 + 120 * t)), (tx * TS, ty * TS, TS, TS))

    def cone(self, fx, poly, col, a=42):
        if len(poly) < 3:
            return
        pygame.draw.polygon(fx, (*col, a), poly)
        x0, y0 = poly[0]
        inner = [(x0, y0)] + [(x0 + (x - x0) * 0.55, y0 + (y - y0) * 0.55) for x, y in poly[1:]]
        pygame.draw.polygon(fx, (*col, a), inner)

    def render_view(self):
        v = self.view
        p = self.player
        v.blit(self.static, (0, 0))
        self.draw_vault(v)
        self.draw_exit(v)
        # darkness with light cut-outs
        d = self.dark
        amb = (3, 5, 13, 170)
        if self.looted:
            amb = (3 + int(24 * (math.sin(self.t * 6) + 1) / 2), 5, 13, 170)
        d.fill(amb)
        sub = pygame.BLEND_RGBA_SUB
        d.blit(light(180, 175), (p.x - 180, p.y - 180), special_flags=sub)
        for gx, gy, gi in self.ghost_now:
            d.blit(light(100, 110), (gx - 100, gy - 100), special_flags=sub)
        for g in self.guards:
            d.blit(light(70, 120), (g.x - 70, g.y - 70), special_flags=sub)
        d.blit(light(110, 120), (VAULT_POS[0] - 110, VAULT_POS[1] - 110), special_flags=sub)
        d.blit(light(120, 110), (PAD_RECT.centerx - 120, PAD_RECT.centery - 120), special_flags=sub)
        v.blit(d, (0, 0))
        # fx layer
        fx = self.fx
        fx.fill((0, 0, 0, 0))
        if self.show_heat or self.state == "result":
            self.draw_heat(fx)
        for i, (ln, tr) in enumerate(self.ghosts):
            if len(tr) > 4:
                pts = tr[::6]
                pygame.draw.lines(fx, (140, 110, 255, 55), False, pts, 2)
        for g in self.guards:
            if g.stun > 0:
                continue
            if g.state == "chase":
                col = (255, 60, 60)
            elif g.state in ("distract", "search"):
                col = (255, 210, 60)
            else:
                col = lerp_col((255, 235, 140), g.COL[g.kind], 0.5)
            self.cone(fx, g.poly, col, 44 if g.state != "chase" else 60)
        for c in self.cams:
            self.cone(fx, c.poly, (255, 60, 60), 40)
        if p.moving and not p.sneak and self.state == "play":
            pygame.draw.circle(fx, (120, 255, 220, 40), (int(p.x), int(p.y)), 95, 1)
        self.particles.draw(fx)
        v.blit(fx, (0, 0))
        self.draw_entities(v)
        if self.alarm_t > 0:
            self.flash.fill((255, 30, 30, int(55 * min(1, self.alarm_t) * (0.6 + 0.4 * math.sin(self.t * 18)))))
            v.blit(self.flash, (0, 0))
        v.blit(self.vig, (0, 0))
        v.blit(self.scanl, (0, 0))

    def draw_entities(self, v):
        t = self.t
        # ghosts
        for gx, gy, gi in self.ghost_now:
            tr = self.ghosts[gi][1]
            f = max(0, self.frame - 1)
            for k in range(1, 6):
                j = f - k * 5
                if j >= 0 and j < len(tr):
                    add_glow(v, tr[j][0], tr[j][1], 14, (110, 80, 255), 0.5 * (1 - k / 6))
            add_glow(v, gx, gy, 38, (120, 90, 255), 0.8)
            fl = 8 + math.sin(t * 14) * 1.2
            pygame.draw.circle(v, (150, 120, 255), (int(gx), int(gy)), int(fl), 2)
            pygame.draw.circle(v, (70, 50, 160), (int(gx), int(gy)), int(fl - 3))
            draw_text(v, "ECHO %d" % self.ghosts[gi][0], self.f_s, (170, 150, 255), (gx, gy - 28), "c")
        # cameras
        for c in self.cams:
            pygame.draw.rect(v, (50, 56, 76), (c.x - 9, c.y - 7, 18, 14), border_radius=3)
            ex, ey = c.x + math.cos(c.ang) * 12, c.y + math.sin(c.ang) * 12
            pygame.draw.line(v, (90, 100, 130), (c.x, c.y), (ex, ey), 4)
            on = (int(t * 3) % 2 == 0) or c.meter > 0.1
            pygame.draw.circle(v, (255, 50, 50) if on else (90, 20, 20), (int(ex), int(ey)), 3)
            if on:
                add_glow(v, ex, ey, 16, (255, 40, 40), 0.7)
            if c.meter > 0.02:
                pygame.draw.rect(v, (50, 20, 20), (c.x - 14, c.y - 18, 28, 4))
                pygame.draw.rect(v, (255, 70, 70), (c.x - 14, c.y - 18, 28 * c.meter, 4))
        # guards
        for g in self.guards:
            col = g.COL[g.kind]
            if g.state == "chase":
                col = (255, 60, 60)
            if g.stun > 0:
                col = (110, 110, 130)
            add_glow(v, g.x, g.y, 36, col, 0.6)
            pygame.draw.circle(v, (10, 12, 20), (int(g.x), int(g.y)), 12)
            pygame.draw.circle(v, col, (int(g.x), int(g.y)), 9)
            fx_, fy_ = math.cos(g.ang), math.sin(g.ang)
            pygame.draw.line(v, (20, 20, 30), (g.x, g.y), (g.x + fx_ * 12, g.y + fy_ * 12), 4)
            pygame.draw.circle(v, (255, 255, 255), (int(g.x + fx_ * 6), int(g.y + fy_ * 6)), 2)
            if g.stun > 0:
                for k in range(3):
                    a = t * 6 + k * 2.1
                    pygame.draw.circle(v, (255, 240, 90), (int(g.x + math.cos(a) * 14), int(g.y - 14 + math.sin(a) * 4)), 3)
            elif g.state == "chase":
                draw_text(v, "!", self.f_l, (255, 70, 70), (g.x, g.y - 38), "c")
            elif g.state in ("distract", "search"):
                draw_text(v, "?", self.f_l, (255, 220, 70), (g.x, g.y - 38), "c")
            if g.meter > 0.02 and g.stun <= 0:
                pygame.draw.rect(v, (40, 20, 20), (g.x - 15, g.y - 22, 30, 4))
                pygame.draw.rect(v, lerp_col((255, 220, 60), (255, 50, 50), g.meter), (g.x - 15, g.y - 22, 30 * g.meter, 4))
        # player
        p = self.player
        for i, (tx, ty) in enumerate(p.trail):
            add_glow(v, tx, ty, 10, (30, 200, 160), 0.25 * i / max(1, len(p.trail)))
        add_glow(v, p.x, p.y, 42, (40, 230, 180), 0.65)
        r = 6 if p.sneak else 9
        if self.looted:
            bx, by = p.x - math.cos(p.ang) * 11, p.y - math.sin(p.ang) * 11
            pygame.draw.circle(v, (240, 190, 50), (int(bx), int(by)), 6)
            pygame.draw.circle(v, (120, 90, 20), (int(bx), int(by)), 6, 2)
        pygame.draw.circle(v, (6, 20, 20), (int(p.x), int(p.y)), r + 3)
        pygame.draw.circle(v, (90, 255, 210) if not p.sneak else (60, 170, 150), (int(p.x), int(p.y)), r)
        pygame.draw.circle(v, (255, 255, 255), (int(p.x + math.cos(p.ang) * r * 0.6), int(p.y + math.sin(p.ang) * r * 0.6)), 2)
        # objective arrow
        if self.state == "play":
            tgt = PAD_RECT.center if self.looted else VAULT_POS
            a = math.atan2(tgt[1] - p.y, tgt[0] - p.x)
            col = (80, 255, 150) if self.looted else (255, 210, 80)
            bob = 26 + math.sin(t * 6) * 2
            tip = (p.x + math.cos(a) * (bob + 8), p.y + math.sin(a) * (bob + 8))
            l1 = (p.x + math.cos(a + 2.6) * 6 + math.cos(a) * bob, p.y + math.sin(a + 2.6) * 6 + math.sin(a) * bob)
            l2 = (p.x + math.cos(a - 2.6) * 6 + math.cos(a) * bob, p.y + math.sin(a - 2.6) * 6 + math.sin(a) * bob)
            pygame.draw.polygon(v, col, [tip, l1, l2])
        # toasts
        for i, (msg, col, life) in enumerate(self.toasts):
            draw_text(v, msg, self.f_m, col, (GW * TS // 2, 10 + i * 24), "c", alpha=int(255 * min(1, life)))

    # ---------------------------------------------------------------- HUD
    def draw_hud(self):
        s = self.screen
        pygame.draw.rect(s, (8, 11, 21), (0, 0, W, OY))
        pygame.draw.line(s, (60, 100, 170), (0, OY - 1), (W, OY - 1), 2)
        draw_text(s, "ECHO HEIST", self.f_l, (90, 255, 210), (16, 6))
        draw_text(s, "LOOP %02d   BANKED %d" % (self.loop, self.banked), self.f_m, (200, 215, 255), (16, 40))
        draw_text(s, "SCORE %06d   BEST %d" % (self.score, self.best), self.f_s, (150, 170, 220), (16, 62))
        # timer
        bx, bw = 330, 480
        frac = clamp(self.t_left / LOOP_TIME, 0, 1)
        col = lerp_col((255, 70, 60), (70, 230, 150), clamp(frac * 1.6, 0, 1))
        pygame.draw.rect(s, (24, 30, 48), (bx, 18, bw, 18), border_radius=9)
        if frac > 0:
            blink = self.t_left < 10 and int(self.t * 6) % 2 == 0
            pygame.draw.rect(s, (255, 255, 255) if blink else col, (bx, 18, int(bw * frac), 18), border_radius=9)
        pygame.draw.rect(s, (90, 120, 190), (bx, 18, bw, 18), 2, border_radius=9)
        draw_text(s, "%04.1fs" % self.t_left, self.f_m, (230, 240, 255), (bx + bw // 2, 17), "c")
        obj = "ESCAPE TO THE EXIT!" if self.looted else "REACH THE VAULT"
        draw_text(s, obj, self.f_m, (80, 255, 150) if self.looted else (255, 210, 80), (bx + bw // 2, 44), "c")
        draw_text(s, "ECHOES %d | AMBUSH %d | TRACKER %s | H=heat" % (
            len(self.ghosts), len(self.deployed), "ON" if self.tracker else "off"),
            self.f_s, (140, 160, 210), (bx + bw // 2, 64), "c")
        # guard memory table
        px = 880
        pygame.draw.line(s, (50, 80, 130), (px - 14, 8), (px - 14, OY - 10), 1)
        draw_text(s, "GUARD MEMORY  (path frequency)", self.f_s, (255, 120, 140), (px, 5))
        pred = self.predicted()
        mx = max(3, max(self.lane_counts))
        for i in range(3):
            y = 24 + i * 17
            draw_text(s, "%-6s" % LANES[i], self.f_s, (200, 215, 255), (px, y), shadow=False)
            pygame.draw.rect(s, (24, 30, 48), (px + 66, y + 2, 170, 10))
            c = self.lane_counts[i]
            pygame.draw.rect(s, (255, 90, 110) if c >= 2 else (230, 170, 70), (px + 66, y + 2, int(170 * c / mx), 10))
            draw_text(s, str(c), self.f_s, (255, 255, 255), (px + 244, y), shadow=False)
            if pred == i:
                draw_text(s, "<< PREDICTED", self.f_s, (255, 90, 110), (px + 268, y), shadow=False)

    # ---------------------------------------------------------------- overlays
    def draw_glitch(self, strength):
        s = self.screen
        for _ in range(int(14 * strength)):
            y = random.randrange(OY, H - 20)
            h = random.randrange(4, 30)
            off = random.randrange(-60, 60)
            strip = s.subsurface((0, y, W, min(h, H - y))).copy()
            s.blit(strip, (off, y))

    def draw_title(self):
        s = self.screen
        t = self.t
        s.blit(self.bg_title, (0, 0))
        hz = 380
        for i in range(-26, 27):
            pygame.draw.line(s, (40, 60, 130), (W // 2 + i * 16, hz), (W // 2 + i * 130, H), 1)
        for k in range(16):
            u = ((k + (t * 0.7) % 1) / 16)
            y = hz + (H - hz) * u ** 2.2
            c = int(30 + 90 * u)
            pygame.draw.line(s, (c // 2, c, 150), (0, y), (W, y), 1)
        # orbiting echoes
        for k in range(5):
            a = t * 0.9 - k * 0.45
            x, y = W // 2 + math.cos(a) * 430, 250 + math.sin(a) * 60
            add_glow(s, x, y, 40, (120, 90, 255), 0.9 * (1 - k / 5))
            pygame.draw.circle(s, (170, 140, 255), (int(x), int(y)), 8 - k)
        add_glow(s, W // 2 + math.cos(t * 0.9 + 3.14) * 430, 250 + math.sin(t * 0.9 + 3.14) * 60, 60, (255, 90, 110), 0.8)
        gl = random.random() < 0.06
        ox = random.choice([-8, 8]) if gl else 3
        draw_text(s, "ECHO HEIST", self.f_xxl, (255, 60, 120), (W // 2 - ox, 150), "c", shadow=False)
        draw_text(s, "ECHO HEIST", self.f_xxl, (60, 230, 255), (W // 2 + ox, 150), "c", shadow=False)
        draw_text(s, "ECHO HEIST", self.f_xxl, (255, 255, 255), (W // 2, 150), "c", shadow=False)
        draw_text(s, "THE GUARDS REMEMBER EVERY LOOP", self.f_l, (170, 190, 255), (W // 2, 262), "c")
        panel(s, pygame.Rect(W // 2 - 400, 420, 800, 200))
        lines = [
            ("WASD / ARROWS  move        SHIFT  sneak (quiet, harder to spot)", (210, 225, 255)),
            ("Grab the VAULT loot, then reach the EXIT before time runs out.", (255, 215, 110)),
            ("Guards log your lanes: used a lane twice? Next time an ambush waits there.", (255, 120, 140)),
            ("Your past run replays as an ECHO - guards chase it, and it can stun them.", (180, 160, 255)),
            ("H heat-map   P pause   M mute   F fullscreen   R memory wipe", (150, 170, 220)),
        ]
        for i, (txt, c) in enumerate(lines):
            draw_text(s, txt, self.f_s, c, (W // 2, 436 + i * 28), "c")
        if int(t * 2) % 2 == 0:
            draw_text(s, "PRESS ENTER TO BEGIN THE FIRST LOOP", self.f_l, (90, 255, 210), (W // 2, 650), "c")

    def draw_briefing(self):
        s = self.screen
        if self.st < 0.8:
            self.draw_glitch(1.0 - self.st / 0.8)
        panel(s, pygame.Rect(120, 300, W - 240, 128), (8, 10, 24), 225, (255, 100, 130))
        draw_text(s, "LOOP %02d  -  THE GUARDS REMEMBER" % self.loop, self.f_l, (255, 120, 140), (W // 2, 308), "c")
        mem = "  |  ".join("%s x%d" % (LANES[i], self.lane_counts[i]) for i in range(3))
        draw_text(s, "Route memory:  " + mem, self.f_m, (210, 225, 255), (W // 2, 346), "c")
        if self.deployed:
            msg = "AMBUSH posted: " + ", ".join(LANES[i] for i in self.deployed)
        else:
            msg = "No ambushes yet - they are still learning (a lane used twice gets an ambush)."
        if self.tracker:
            msg += "   TRACKER hunts your hot zones."
        draw_text(s, msg, self.f_s, (255, 180, 120), (W // 2, 374), "c")
        draw_text(s, "Echoes replaying: %d   |   Press SPACE to start the loop" % len(self.ghosts),
                  self.f_s, (170, 150, 255), (W // 2, 398), "c")

    def draw_result(self):
        s = self.screen
        titles = {"escaped": ("HEIST COMPLETE", (90, 255, 160)),
                  "caught": ("BUSTED", (255, 80, 90)),
                  "time": ("THE LOOP COLLAPSED", (255, 190, 70))}
        txt, col = titles[self.result]
        panel(s, pygame.Rect(W // 2 - 330, 230, 660, 270), (8, 10, 24), 235, col)
        draw_text(s, txt, self.f_xl, col, (W // 2, 246), "c")
        for i, line in enumerate(self.result_info):
            draw_text(s, line, self.f_m, (215, 228, 255), (W // 2, 318 + i * 30), "c")
        if int(self.t * 2) % 2 == 0:
            draw_text(s, "SPACE  -  rewind time", self.f_m, (90, 255, 210), (W // 2, 452), "c")
        draw_text(s, "(heat-map shows where the guards will hunt)", self.f_s, (150, 170, 220), (W // 2, 478), "c")

    def draw(self):
        s = self.screen
        if self.state == "title":
            self.draw_title()
            return
        s.fill((0, 0, 0))
        self.render_view()
        ox = oy = 0
        if self.shake > 0:
            m = int(self.shake * 14)
            ox, oy = random.randint(-m, m), random.randint(-m, m)
        s.blit(self.view, (ox, OY + oy))
        self.draw_hud()
        if self.state == "briefing":
            self.draw_briefing()
        elif self.state == "result":
            self.draw_result()
        elif self.state == "pause":
            panel(s, pygame.Rect(W // 2 - 220, 280, 440, 150))
            draw_text(s, "PAUSED", self.f_xl, (255, 255, 255), (W // 2, 296), "c")
            draw_text(s, "P / ESC resume    Q quit", self.f_m, (170, 190, 255), (W // 2, 366), "c")


# ----------------------------------------------------------------------------
def main():
    pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()
    pygame.display.set_caption("ECHO HEIST")
    try:
        screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
    except Exception:
        screen = pygame.display.set_mode((W, H))
    game = Game(screen)
    clock = pygame.time.Clock()
    while True:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            game.handle_event(e)
        game.update(pygame.key.get_pressed())
        game.draw()
        pygame.display.flip()
        clock.tick(FPS)


if __name__ == "__main__":
    main()