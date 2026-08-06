<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>银河快报，自动送到群里</Text>
  </Box>
  <Box style={{ height:504, flexDirection:'row', gap:28 }}>
    <Box style={{ width:'60%', flexDirection:'column', justifyContent:'space-between' }}>
      {[
        { n:'1', ic:'comment-dots', c:'#3D9BE9', t:'订阅当前群', d:'管理员一条 /银河快报订阅，建立监听基线' },
        { n:'2', ic:'satellite-dish', c:'#F5A623', t:'后台轮询监听', d:'定时拉取 B站动态，匹配「银河快报」关键词' },
        { n:'3', ic:'paper-plane', c:'#5BA85B', t:'主动推送', d:'新一期正文 + 图片 + 出处，自动发到群' },
      ].map((it, i) => (
        <Box key={i} style={{ flexDirection:'row', alignItems:'center', gap:20, background:'#10213B', borderRadius:14, padding:'18px 24px' }}>
          <Box style={{ width:54, height:54, borderRadius:50, background:'rgba(61,155,233,0.12)', justifyContent:'center', alignItems:'center' }}>
            <Text style={{ fontSize:24, fontWeight:'bold', color:it.c }}>{it.n}</Text>
          </Box>
          <Box style={{ flex:1 }}>
            <Text style={{ fontSize:22, fontWeight:'bold', color:'#EAF1FB' }}>{it.t}</Text>
            <Text style={{ fontSize:17, color:'#9FB3CC', lineHeight:1.5, marginTop:4 }}>{it.d}</Text>
          </Box>
        </Box>
      ))}
    </Box>
    <Box style={{ width:'40%', background:'linear-gradient(160deg,#16335C 0%,#0B1424 100%)', border:'2px solid #F5A623', borderRadius:16, padding:32, justifyContent:'center' }}>
      <FAIcon name='bell' style={{ fill:'#F5A623', width:46, height:46, marginBottom:16 }} />
      <Text style={{ fontSize:27, fontWeight:'bold', color:'#F5A623', lineHeight:1.4 }}>B站银河快报{'\n'}自动送达</Text>
      <Box style={{ width:80, height:3, background:'#3D9BE9', margin:'18px 0' }} />
      <Text style={{ fontSize:19, color:'#EAF1FB', lineHeight:1.9 }}>
        · 不漏任何一期战报{'\n'}· 动态 ID 去重，不刷屏{'\n'}· 保留原作者出处
      </Text>
    </Box>
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>08 / 12</Text>
  </Box>
</Slide>
