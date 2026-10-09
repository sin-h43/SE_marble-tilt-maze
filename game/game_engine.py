import math
import pygame
from .marble import Marble
from .wall import Wall
from .sound import SoundManager

# Game Engine

WHITE = (255, 255, 255)
DARK = (40, 40, 50)
WALL_COLOR = (90, 90, 110)
GOAL_COLOR = (60, 200, 120)
LOSE_COLOR = (230, 90, 90)
GREY = (170, 170, 185)

# Difficulty presets: tilt strength, friction and time limit (ms)
DIFFICULTIES = {
    "Easy":   {"tilt_strength": 0.45, "friction": 0.030, "time_limit_ms": 60000},
    "Medium": {"tilt_strength": 0.60, "friction": 0.020, "time_limit_ms": 45000},
    "Hard":   {"tilt_strength": 0.85, "friction": 0.010, "time_limit_ms": 30000},
}
DIFFICULTY_KEYS = {
    pygame.K_1: "Easy", pygame.K_KP1: "Easy",
    pygame.K_2: "Medium", pygame.K_KP2: "Medium",
    pygame.K_3: "Hard", pygame.K_KP3: "Hard",
}

class GameEngine:
    def __init__(self, width, height):
        self.width = width
        self.height = height

        self.start_pos = (50, 50)
        self.marble = Marble(*self.start_pos)
        self.max_speed = 9

        self.walls = self._build_maze()
        self.goal_x, self.goal_y, self.goal_radius = width - 60, height - 60, 22

        self.difficulty = "Medium"
        self._apply_difficulty(self.difficulty)
        self.start_ticks = pygame.time.get_ticks()

        self.font = pygame.font.SysFont("Arial", 26)
        self.title_font = pygame.font.SysFont("Arial", 56, bold=True)
        self.small_font = pygame.font.SysFont("Arial", 22)
        self.game_over = False
        self.result = None  # "solved" or "timeout"
        self.finish_time_ms = None
        self.elapsed_ms = 0          # frozen once the round ends
        self.quit_requested = False  # main.py exits the loop when True

        self.sounds = SoundManager()
        self.last_bounce_ms = -1000
        self.bounce_min_speed = 1.2  # ignore the tiny "resting on a wall" contacts
        self._impact_speed = 0.0

    def _apply_difficulty(self, name):
        settings = DIFFICULTIES[name]
        self.difficulty = name
        self.tilt_strength = settings["tilt_strength"]
        self.friction = settings["friction"]
        self.time_limit_ms = settings["time_limit_ms"]

    def restart(self, difficulty):
        """Start a fresh round using the chosen difficulty preset."""
        self._apply_difficulty(difficulty)
        self.marble = Marble(*self.start_pos)
        self.game_over = False
        self.result = None
        self.finish_time_ms = None
        self.elapsed_ms = 0
        self.start_ticks = pygame.time.get_ticks()

    def _build_maze(self):
        walls = []
        t = 16  # wall thickness

        # outer boundary
        walls.append(Wall(0, 0, self.width, t))
        walls.append(Wall(0, self.height - t, self.width, t))
        walls.append(Wall(0, 0, t, self.height))
        walls.append(Wall(self.width - t, 0, t, self.height))

        # a few internal walls forming a simple winding path
        walls.append(Wall(0, 140, self.width - 140, t))
        walls.append(Wall(140, 260, self.width - 140, t))
        walls.append(Wall(0, 380, self.width - 140, t))

        return walls

    def handle_event(self, event):
        # Movement is driven by the continuous mouse position (handle_input);
        # events are only needed for the end screen.
        if self.game_over and event.type == pygame.KEYDOWN:
            if event.key in DIFFICULTY_KEYS:
                self.restart(DIFFICULTY_KEYS[event.key])
            elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                self.quit_requested = True

    def handle_input(self):
        if self.game_over:
            return

        mouse_x, mouse_y = pygame.mouse.get_pos()
        dx = mouse_x - self.width // 2
        dy = mouse_y - self.height // 2
        dist = max(1, (dx ** 2 + dy ** 2) ** 0.5)
        ax = (dx / dist) * self.tilt_strength
        ay = (dy / dist) * self.tilt_strength
        self.marble.vx += ax
        self.marble.vy += ay

    def update(self):
        if self.game_over:
            return

        elapsed = pygame.time.get_ticks() - self.start_ticks
        self.elapsed_ms = elapsed
        if elapsed >= self.time_limit_ms:
            self.elapsed_ms = self.time_limit_ms
            self.game_over = True
            self.result = "timeout"
            self.sounds.play_timeout()
            return

        self.marble.vx *= (1 - self.friction)
        self.marble.vy *= (1 - self.friction)

        speed = (self.marble.vx ** 2 + self.marble.vy ** 2) ** 0.5
        if speed > self.max_speed:
            scale = self.max_speed / speed
            self.marble.vx *= scale
            self.marble.vy *= scale

        self.marble.x += self.marble.vx
        self.marble.y += self.marble.vy

        self._impact_speed = 0.0
        self._resolve_wall_collisions()
        self._play_bounce_sound_if_needed()

        gx = self.goal_x - self.marble.x
        gy = self.goal_y - self.marble.y
        if (gx ** 2 + gy ** 2) ** 0.5 <= self.goal_radius:
            self.game_over = True
            self.result = "solved"
            self.finish_time_ms = elapsed
            self.sounds.play_win()

    def _resolve_wall_collisions(self):
        """True circle-vs-rectangle collision.

        For every wall we find the point on the rectangle that is closest to
        the marble's centre. If that point is closer than the marble's radius
        the round marble is genuinely touching the wall. Near a corner the
        closest point *is* the corner, so there is no phantom bounce off the
        empty space that the old bounding-square test produced.
        """
        m = self.marble
        restitution = 0.3  # same bounciness as the original (-0.3)

        for wall in self.walls:
            r = wall.rect()

            # Closest point on the rectangle to the circle centre
            closest_x = max(r.left, min(m.x, r.right))
            closest_y = max(r.top, min(m.y, r.bottom))
            dx = m.x - closest_x
            dy = m.y - closest_y
            dist_sq = dx * dx + dy * dy

            if dist_sq >= m.radius * m.radius:
                continue  # not touching

            if dist_sq > 0:
                dist = dist_sq ** 0.5
                nx, ny = dx / dist, dy / dist
                penetration = m.radius - dist
            else:
                # Centre is inside the rectangle (e.g. after a very fast
                # move): push out through the nearest face.
                gaps = {
                    (-1, 0): m.x - r.left,
                    (1, 0): r.right - m.x,
                    (0, -1): m.y - r.top,
                    (0, 1): r.bottom - m.y,
                }
                (nx, ny), face_gap = min(gaps.items(), key=lambda kv: kv[1])
                penetration = face_gap + m.radius

            # Push the marble out of the wall along the contact normal
            m.x += nx * penetration
            m.y += ny * penetration

            # Reflect only the velocity component heading into the wall
            vn = m.vx * nx + m.vy * ny
            if vn < 0:
                self._impact_speed = max(self._impact_speed, -vn)
                m.vx -= (1 + restitution) * vn * nx
                m.vy -= (1 + restitution) * vn * ny

    def _play_bounce_sound_if_needed(self):
        now = pygame.time.get_ticks()
        if self._impact_speed >= self.bounce_min_speed and now - self.last_bounce_ms > 100:
            self.sounds.play_bounce(self._impact_speed / self.max_speed)
            self.last_bounce_ms = now

    def render(self, screen):
        screen.fill(DARK)

        for wall in self.walls:
            pygame.draw.rect(screen, WALL_COLOR, wall.rect())

        pygame.draw.circle(screen, GOAL_COLOR, (self.goal_x, self.goal_y), self.goal_radius)
        pygame.draw.circle(screen, WHITE, (int(self.marble.x), int(self.marble.y)), self.marble.radius)

        seconds_left = max(0, math.ceil((self.time_limit_ms - self.elapsed_ms) / 1000))
        timer_text = self.font.render(f"Time: {seconds_left}s", True, WHITE)
        screen.blit(timer_text, (24, 22))
        level_text = self.small_font.render(self.difficulty, True, GREY)
        screen.blit(level_text, level_text.get_rect(topright=(self.width - 24, 26)))

        if self.game_over:
            self._render_game_over(screen)

    def _render_game_over(self, screen):
        overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 175))
        screen.blit(overlay, (0, 0))

        if self.result == "solved":
            title, color = "Maze Solved!", GOAL_COLOR
            detail = f"Finish time: {self.finish_time_ms / 1000:.1f}s"
        else:
            title, color = "Time's Up!", LOSE_COLOR
            detail = "The maze was not solved in time."

        cx = self.width // 2
        cy = self.height // 2
        self._blit_centered(screen, self.title_font.render(title, True, color), cx, cy - 85)
        self._blit_centered(screen, self.font.render(detail, True, WHITE), cx, cy - 25)
        self._blit_centered(screen, self.small_font.render("Play again - choose a difficulty:", True, WHITE), cx, cy + 30)

        options = "1  Easy (60s)     2  Medium (45s)     3  Hard (30s)"
        self._blit_centered(screen, self.small_font.render(options, True, GOAL_COLOR), cx, cy + 65)
        self._blit_centered(screen, self.small_font.render("ESC / Q  Exit", True, GREY), cx, cy + 105)

    @staticmethod
    def _blit_centered(screen, surface, cx, cy):
        screen.blit(surface, surface.get_rect(center=(cx, cy)))
