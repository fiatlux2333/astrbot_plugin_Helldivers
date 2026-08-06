<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>自带中文的情报卡</Text>
  </Box>
  <Box style={{ height:504, flexDirection:'column', gap:18 }}>
    <Box style={{ height:228, flexDirection:'row', alignItems:'center', gap:18 }}>
      <Box style={{ width:'38%', background:'#10213B', border:'1px solid #1E3A5F', borderRadius:12, padding:20 }}>
        <Text style={{ fontSize:14, color:'#8FA3BF', fontFamily:'Consolas', marginBottom:8 }}>BEFORE · EN</Text>
        <Text style={{ fontSize:19, color:'#9FB3CC', lineHeight:1.6 }}>MAJOR ORDER{'\n'}Liberate Moorwoe{'\n'}Defense Campaign</Text>
      </Box>
      <FAIcon name='arrow-right' style={{ fill:'#3D9BE9', width:40, height:40 }} />
      <Box style={{ flex:1, background:'linear-gradient(135deg,#16335C 0%,#0B1424 100%)', border:'1px solid #3D9BE9', borderRadius:12, padding:20 }}>
        <Text style={{ fontSize:14, color:'#3D9BE9', fontFamily:'Consolas', marginBottom:8 }}>AFTER · 中文</Text>
        <Text style={{ fontSize:22, fontWeight:'bold', color:'#EAF1FB', lineHeight:1.6 }}>重要指令{'\n'}解放摩尔维{'\n'}防御战役 · 进度 62%</Text>
      </Box>
    </Box>
    <Box style={{ flex:1, flexDirection:'row', gap:18 }}>
      {[
        { ic:'palette', c:'#3D9BE9', t:'Pillow 本地渲染', d:'战争数据由 Pillow 绘制为中文卡片，离线可靠' },
        { ic:'language', c:'#F5A623', t:'Companion 翻译截图', d:'Playwright 抓原网页并回写中文，原汁原味' },
        { ic:'book', c:'#5BA85B', t:'HD2 术语本地化', d:'内置军事广播语气术语库，读起来像官方' },
      ].map((it, i) => (
        <Box key={i} style={{ flex:1, flexDirection:'column', justifyContent:'space-between', background:'#10213B', borderRadius:14, padding:'22px 22px 18px' }}>
          <Box style={{ width:52, height:52, borderRadius:12, background:'rgba(255,255,255,0.05)', justifyContent:'center', alignItems:'center' }}>
            <FAIcon name={it.ic} style={{ fill:it.c, width:28, height:28 }} />
          </Box>
          <Box style={{ marginTop:14 }}>
            <Text style={{ fontSize:21, fontWeight:'bold', color:'#EAF1FB' }}>{it.t}</Text>
            <Text style={{ fontSize:16, color:'#9FB3CC', lineHeight:1.5, marginTop:6 }}>{it.d}</Text>
          </Box>
        </Box>
      ))}
    </Box>
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>06 / 12</Text>
  </Box>
</Slide>
