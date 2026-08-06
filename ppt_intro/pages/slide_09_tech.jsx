<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>看不见的技术底座</Text>
  </Box>
  <Box style={{ height:504, flexDirection:'row', gap:32 }}>
    <Box style={{ width:'34%', background:'linear-gradient(160deg,#16335C 0%,#0B1424 100%)', borderRadius:16, padding:32, justifyContent:'center' }}>
      <FAIcon name='shield-alt' style={{ fill:'#F5A623', width:56, height:56, marginBottom:18 }} />
      <Text style={{ fontSize:24, fontWeight:'bold', color:'#EAF1FB', lineHeight:1.4 }}>稳，才敢{'\n'}交给群友</Text>
      <Text style={{ fontSize:15, color:'#8FA3BF', lineHeight:1.6, marginTop:12 }}>异步、限流、安全校验，一个都不少。</Text>
    </Box>
    <Box style={{ flex:1, flexDirection:'column', justifyContent:'space-between', padding:'6px 0' }}>
      {[
        { ic:'bolt', c:'#3D9BE9', t:'异步缓存与后台刷新', d:'内存 + 磁盘双层缓存，定时刷新，群内秒回' },
        { ic:'tachometer-alt', c:'#F5A623', t:'全局限流与重试退避', d:'最小请求间隔、429 冷却、失败自动退避' },
        { ic:'lock', c:'#5BA85B', t:'SSRF 防护', d:'Companion 路由白名单，杜绝任意网页截图' },
        { ic:'language', c:'#3D9BE9', t:'AI 翻译', d:'内置 / OpenAI 兼容，遵循 HD2 术语本地化' },
        { ic:'image', c:'#F5A623', t:'图片安全校验', d:'大小 / 像素 / 来源域名限制，远程缓存隔离' },
      ].map((it, i) => (
        <Box key={i} style={{ flexDirection:'row', alignItems:'center', gap:18, background:'#10213B', borderRadius:12, padding:'14px 22px' }}>
          <Box style={{ width:46, height:46, borderRadius:12, background:'rgba(255,255,255,0.05)', justifyContent:'center', alignItems:'center' }}>
            <FAIcon name={it.ic} style={{ fill:it.c, width:24, height:24 }} />
          </Box>
          <Box style={{ flex:1 }}>
            <Text style={{ fontSize:20, fontWeight:'bold', color:'#EAF1FB' }}>{it.t}</Text>
            <Text style={{ fontSize:15, color:'#9FB3CC' }}>{it.d}</Text>
          </Box>
        </Box>
      ))}
    </Box>
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>09 / 12</Text>
  </Box>
</Slide>
