/**
 * 首页 hero 插画（搬运自 prototypes/speakup 的 heroArt SVG）：
 * 耳机 + 对话气泡 + 书本，口语探索意象。
 */
function HeroArt() {
  return (
    <svg
      viewBox="0 0 370 320"
      role="img"
      aria-label="耳机、对话气泡和书本组成的口语探索插画"
      className="h-full w-full"
    >
      <defs>
        <linearGradient id="bubble" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#ffba88" />
          <stop offset="1" stopColor="#ed8751" />
        </linearGradient>
        <linearGradient id="hp" x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#477b5f" />
          <stop offset="1" stopColor="#24513e" />
        </linearGradient>
        <linearGradient id="book" x1="1" y1="1">
          <stop stopColor="#c0d8b1" />
          <stop offset="1" stopColor="#87b490" />
        </linearGradient>
        <filter id="soft">
          <feGaussianBlur stdDeviation="7" />
        </filter>
        <filter id="shadow" x="-40%" y="-40%" width="180%" height="180%">
          <feDropShadow
            dx="0"
            dy="8"
            stdDeviation="6"
            floodColor="#28563c"
            floodOpacity=".14"
          />
        </filter>
      </defs>
      <ellipse
        cx="209"
        cy="269"
        rx="112"
        ry="16"
        fill="#a7bfa2"
        opacity=".32"
        filter="url(#soft)"
      />
      <ellipse
        cx="191"
        cy="172"
        rx="141"
        ry="110"
        fill="none"
        stroke="#bfd0b8"
        strokeDasharray="3 6"
        transform="rotate(-28 191 172)"
      />
      <circle cx="305" cy="192" r="8" fill="#acc7a3" />
      <circle cx="61" cy="146" r="5" fill="#f5bc87" />
      <path
        d="m280 44 5 13 14 1-11 9 4 14-12-8-11 8 3-14-11-9 14-1Z"
        fill="#e8c973"
        transform="rotate(12 280 60)"
      />
      <path d="M95 247 194 212l103 20-97 41Z" fill="#396949" />
      <path d="m96 231 98-29 103 17v14l-97 35-104-21Z" fill="#faf8e9" />
      <path
        d="m101 238 98 23 92-32M103 243l97 22 88-30"
        fill="none"
        stroke="#d4d7ba"
      />
      <path d="M88 225q45-18 96-11l15 40q-51-17-99-8Z" fill="url(#book)" />
      <path d="M184 214q54-20 108-6l12 23q-58-4-105 23Z" fill="#d2e1c1" />
      <path d="m184 214 15 40" stroke="#719779" fill="none" />
      <path
        d="m113 226 52-1m-47 11 49-1m44-12 49-6m-44 15 48-6"
        stroke="#719979"
        strokeWidth="2"
        opacity=".45"
      />
      <g transform="rotate(-16 186 150)" filter="url(#shadow)">
        <path
          d="M117 171v-38a66 66 0 0 1 132 0v38"
          fill="none"
          stroke="#244e3b"
          strokeWidth="21"
        />
        <path
          d="M118 132a65 65 0 0 1 130 0"
          fill="none"
          stroke="#689271"
          strokeWidth="14"
        />
        <path
          d="M120 112a66 66 0 0 1 128 20"
          fill="none"
          stroke="#90af87"
          strokeWidth="4"
          opacity=".75"
        />
        <rect x="100" y="144" width="38" height="65" rx="17" fill="url(#hp)" />
        <rect x="110" y="151" width="17" height="49" rx="8" fill="#5e8765" />
        <rect x="230" y="144" width="38" height="65" rx="17" fill="url(#hp)" />
        <rect x="239" y="151" width="17" height="49" rx="8" fill="#628a66" />
      </g>
      <g transform="rotate(9 225 117)" filter="url(#shadow)">
        <path
          d="M166 71h95a22 22 0 0 1 22 22v46a23 23 0 0 1-23 23h-21l-24 21 3-21h-52a22 22 0 0 1-22-22V94a23 23 0 0 1 22-23Z"
          fill="url(#bubble)"
        />
        <path
          d="M165 77h92"
          stroke="#ffd6ac"
          strokeWidth="3"
          strokeLinecap="round"
          opacity=".7"
        />
        <g fill="#fff4dc">
          <rect x="175" y="107" width="8" height="19" rx="4" />
          <rect x="192" y="98" width="8" height="38" rx="4" />
          <rect x="209" y="89" width="8" height="54" rx="4" />
          <rect x="226" y="103" width="8" height="27" rx="4" />
          <rect x="243" y="110" width="8" height="14" rx="4" />
        </g>
      </g>
      <path
        d="m70 204 3 9 10 1-8 6 3 10-8-6-8 6 3-10-8-6 10-1Z"
        fill="#f4d67e"
        transform="rotate(-16 70 216)"
      />
      <path
        d="m321 119 10-7m-10 21 14 1m-26-26 3-13"
        stroke="#709279"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

export default HeroArt
