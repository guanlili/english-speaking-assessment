/**
 * 主题插画（搬运自 prototypes/speakup 的 topicArt SVG，按主题名映射）。
 * 6 幅：pets / school / weekend / food / future / friends；未匹配回退 pets。
 */

const ART: Record<string, React.ReactNode> = {
  pets: (
    <>
      <rect width="320" height="180" fill="#f3eadc" />
      <circle cx="254" cy="31" r="62" fill="#e7dbc7" />
      <path d="M28 166q20-47 51-40t46 40" fill="#b9c6aa" />
      <path
        d="m67 148-8-55m7 32-17-15m15 3 15-15"
        stroke="#607c60"
        strokeWidth="3"
        fill="none"
      />
      <ellipse cx="185" cy="158" rx="70" ry="10" fill="#d4c5ad" />
      <path
        d="M158 131q-7-34 12-58l21 2q26 23 22 61l14 18h-71Z"
        fill="#c18954"
      />
      <path
        d="M172 77q-19-17-29 2l1 41q15 7 20-27m39-16q24-6 27 9l-11 35q-13 5-15-13"
        fill="#78583e"
      />
      <ellipse cx="187" cy="92" rx="28" ry="24" fill="#d9aa70" />
      <ellipse cx="187" cy="105" rx="17" ry="13" fill="#f4dbc0" />
      <ellipse cx="187" cy="100" rx="7" ry="5" fill="#3e4638" />
      <circle cx="176" cy="89" r="2.4" fill="#354132" />
      <circle cx="199" cy="89" r="2.4" fill="#354132" />
      <path d="M183 110q4 7 8 0" stroke="#6f4a3f" strokeWidth="2" fill="none" />
      <path d="m167 118 36 4" stroke="#557461" strokeWidth="7" />
      <circle cx="186" cy="124" r="5" fill="#ebcb74" />
      <path
        d="M154 139q-25-6-25-24"
        fill="none"
        stroke="#c18954"
        strokeWidth="13"
        strokeLinecap="round"
      />
      <circle cx="266" cy="140" r="13" fill="#dc8761" />
      <path d="m253 138 25 5" stroke="#f2c0a3" strokeWidth="3" />
    </>
  ),
  school: (
    <>
      <rect width="320" height="180" fill="#e4eddc" />
      <circle cx="64" cy="56" r="47" fill="#d3e0c9" />
      <path d="M30 157h271" stroke="#c2d2b4" strokeWidth="2" />
      <path d="M220 65h45v91h-45Z" fill="#acbda2" />
      <path d="M210 73h65V56h-65Z" fill="#789779" />
      <path
        d="M223 86h9m12 0h9m-30 17h9m12 0h9m-30 17h9m12 0h9"
        stroke="#e9f0df"
        strokeWidth="6"
      />
      <g transform="rotate(-10 154 105)">
        <rect x="81" y="82" width="123" height="64" rx="5" fill="#6a8c73" />
        <rect x="83" y="81" width="116" height="55" rx="4" fill="#fbf7df" />
        <path d="M140 85v45" stroke="#dfd9b7" />
        <path
          d="M83 76q26-8 57 4v52q-28-12-57-5Zm57 4q31-12 59-4v51q-29-5-59 5Z"
          fill="#f8f5e4"
        />
        <path
          d="m94 88 33 4m-33 6 33 4m-33 6 33 4m25-19 35-5m-35 15 35-5m-35 15 35-5"
          stroke="#b5c0a3"
          strokeWidth="2"
        />
      </g>
      <path d="m205 91 22-53 7 3-22 53-7 5Z" fill="#e9ad65" />
      <path d="m205 91 7 3-7 5Z" fill="#40563f" />
      <path d="m67 37 2 7 7 2-7 2-2 7-2-7-7-2 7-2Z" fill="#779274" />
    </>
  ),
  weekend: (
    <>
      <rect width="320" height="180" fill="#e5eaf3" />
      <circle cx="257" cy="39" r="25" fill="#f2cf80" />
      <path d="M0 136 91 61l73 80 63-60 93 61v38H0Z" fill="#c0cbdc" />
      <path d="m0 160 101-46 61 51 66-38 92 44v9H0Z" fill="#9aafc1" />
      <path d="M142 79h48v68h-48Z" fill="#ee9b72" />
      <path
        d="M150 80v-8q16-20 32 0v8"
        fill="none"
        stroke="#916751"
        strokeWidth="6"
      />
      <rect x="132" y="82" width="68" height="77" rx="14" fill="#eaa27d" />
      <rect x="141" y="109" width="49" height="38" rx="8" fill="#f1be95" />
      <path
        d="M148 119h35m-22-25h12"
        stroke="#a46f54"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <path
        d="M132 98h-7v44m75-44h7v44"
        stroke="#94634f"
        strokeWidth="5"
        fill="none"
      />
      <path
        d="m79 89 4-31 16 5-20 26 30-11-5-16"
        fill="#fbf4e4"
        stroke="#71899a"
        strokeWidth="1.5"
      />
      <path d="m73 94-21 19" stroke="#8d9eae" strokeDasharray="3 4" />
    </>
  ),
  food: (
    <>
      <rect width="320" height="180" fill="#f6e8d9" />
      <circle cx="70" cy="38" r="52" fill="#efdabf" />
      <ellipse cx="166" cy="149" rx="85" ry="12" fill="#dbcab2" />
      <ellipse cx="166" cy="128" rx="78" ry="30" fill="#fff9e9" />
      <ellipse cx="166" cy="128" rx="60" ry="21" fill="#e4d6bb" />
      <path d="M119 126v-42q44-43 90 0v42Z" fill="#d7a16e" />
      <path d="M127 121V86q38-31 74 0v35Z" fill="#f5d8a7" />
      <path d="M148 91q16-15 31 0v17h-31Z" fill="#fbf0c9" />
      <circle cx="241" cy="102" r="22" fill="#bf7257" />
      <path d="m239 81 4-12" stroke="#5d7954" strokeWidth="4" />
      <path d="M242 78q16-17 23-7-9 12-23 7" fill="#7f9b68" />
    </>
  ),
  future: (
    <>
      <rect width="320" height="180" fill="#e3ece5" />
      <circle cx="251" cy="40" r="29" fill="#d0dfd2" />
      <path d="m158 123-17 32 22-7 14 10 6-33" fill="#e8b668" />
      <path d="M146 84q15-43 39-48 29 30 21 68l-21 33-41-13Z" fill="#f9f5e5" />
      <path d="m178 41 7-5q13 13 18 30Z" fill="#e59b73" />
      <path d="m146 85-28 28 25 11m63-21 8 35-29-1" fill="#75a08b" />
      <circle cx="177" cy="88" r="16" fill="#6e9582" />
      <circle cx="177" cy="88" r="10" fill="#c8dfd0" />
      <path
        d="m89 52 4 10 10 3-10 3-4 10-3-10-10-3 10-3m169 58 3 8 8 3-8 3-3 8-3-8-8-3 8-3"
        fill="#d2b768"
      />
      <path d="m106 145 15-15m100 36 15-15" stroke="#a6bbae" strokeWidth="2" />
    </>
  ),
  friends: (
    <>
      <rect width="320" height="180" fill="#f0e7df" />
      <circle cx="271" cy="43" r="52" fill="#e5d4c6" />
      <ellipse cx="160" cy="157" rx="86" ry="10" fill="#ddcaba" />
      <path d="M81 154v-35q35-24 67 0v35" fill="#6e947b" />
      <circle cx="115" cy="83" r="28" fill="#eac19c" />
      <path
        d="M86 80q-5-35 26-32 35-5 33 38-14-6-25-23-6 13-34 17"
        fill="#5b5448"
      />
      <circle cx="106" cy="84" r="2" fill="#485346" />
      <circle cx="125" cy="84" r="2" fill="#485346" />
      <path d="m110 96 10 0" stroke="#a77055" strokeWidth="2" />
      <path d="M164 154v-35q35-24 67 0v35" fill="#de9c79" />
      <circle cx="198" cy="83" r="27" fill="#e7ba92" />
      <path
        d="M172 82q-8-35 25-34 31 0 29 35l-11-12-16-7-23 14"
        fill="#625246"
      />
      <circle cx="190" cy="84" r="2" fill="#485346" />
      <circle cx="207" cy="84" r="2" fill="#485346" />
      <path d="M191 95q7 7 13-1" stroke="#a77055" strokeWidth="2" fill="none" />
      <path
        d="m134 126 23 13 20-15"
        stroke="#e8be99"
        strokeWidth="11"
        strokeLinecap="round"
        fill="none"
      />
      <path d="m152 43 4 8 9 1-7 6 2 9-8-5-8 5 2-9-7-6 9-1Z" fill="#ccad67" />
    </>
  ),
}

const KEYWORDS: Array<[RegExp, string]> = [
  [/pet|dog|cat|animal/i, "pets"],
  [/school|class|campus|study/i, "school"],
  [/weekend|travel|trip|plan|museum/i, "weekend"],
  [/food|eat|meal|cook|drink/i, "food"],
  [/future|dream|job|hope|plan/i, "future"],
  [/friend|family|people|meet/i, "friends"],
]

function artKey(topic?: string | null): string {
  for (const [pattern, key] of KEYWORDS) {
    if (topic && pattern.test(topic)) return key
  }
  return "pets"
}

function TopicArt({ topic }: { topic?: string | null }) {
  return (
    <svg
      viewBox="0 0 320 180"
      preserveAspectRatio="xMidYMid slice"
      role="img"
      aria-label={`${topic ?? "英语"} 主题插画`}
      className="h-full w-full"
    >
      {ART[artKey(topic)]}
    </svg>
  )
}

export default TopicArt
