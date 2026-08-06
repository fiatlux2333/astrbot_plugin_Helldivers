<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>一句话，调出全部战况</Text>
  </Box>
  <Box style={{ height:504, flexDirection:'row', gap:28 }}>
    <Box style={{ width:'55%', background:'#0B1424', borderRadius:14, border:'1px solid #16335C', overflow:'hidden' }}>
      <Box style={{ height:42, background:'#16335C', flexDirection:'row', alignItems:'center', gap:8, paddingLeft:16 }}>
        <Box style={{ width:12, height:12, borderRadius:50, background:'#D64545' }} />
        <Box style={{ width:12, height:12, borderRadius:50, background:'#F5A623' }} />
        <Box style={{ width:12, height:12, borderRadius:50, background:'#5BA85B' }} />
        <Text style={{ fontSize:15, color:'#8FA3BF', marginLeft:10, fontFamily:'Consolas' }}>helldivers@companion — 指令终端</Text>
      </Box>
      <Box style={{ padding:'20px 24px', gap:12, flexDirection:'column' }}>
        {[
          { c:'#5BA85B', t:'/dashboard', d:'银河战争总览' },
          { c:'#3D9BE9', t:'/order', d:'当前 Major Order' },
          { c:'#3D9BE9', t:'/dss', d:'民主空间站状态' },
          { c:'#F5A623', t:'/map', d:'银河战争地图' },
          { c:'#F5A623', t:'/planet', d:'星球详情（中/英/编号）' },
          { c:'#5BA85B', t:'/银河快报', d:'订阅战报推送' },
        ].map((it, i) => (
          <Box key={i} style={{ flexDirection:'row', alignItems:'baseline', gap:12 }}>
            <Text style={{ fontSize:20, fontFamily:'Consolas', color:it.c, width:150 }}>{it.t}</Text>
            <Text style={{ fontSize:18, color:'#9FB3CC' }}>{it.d}</Text>
          </Box>
        ))}
      </Box>
    </Box>
    <Box style={{ flex:1, flexDirection:'column', justifyContent:'center', gap:22 }}>
      <Box>
        <Text style={{ fontSize:24, fontWeight:'bold', color:'#EAF1FB' }}>三大类指令</Text>
        <Text style={{ fontSize:18, color:'#9FB3CC', lineHeight:1.6, marginTop:6 }}>12+ 条指令覆盖战争全貌，输入即出图。</Text>
      </Box>
      <Box style={{ flexDirection:'row', alignItems:'center', gap:14 }}>
        <FAIcon name='chart-bar' style={{ fill:'#3D9BE9', width:30, height:30 }} />
        <Text style={{ fontSize:19, color:'#EAF1FB' }}>数据查询：总览 / 统计 / 战线</Text>
      </Box>
      <Box style={{ flexDirection:'row', alignItems:'center', gap:14 }}>
        <FAIcon name='image' style={{ fill:'#F5A623', width:30, height:30 }} />
        <Text style={{ fontSize:19, color:'#EAF1FB' }}>情报渲染：新闻 / DSS / 星球</Text>
      </Box>
      <Box style={{ flexDirection:'row', alignItems:'center', gap:14 }}>
        <FAIcon name='bell' style={{ fill:'#5BA85B', width:30, height:30 }} />
        <Text style={{ fontSize:19, color:'#EAF1FB' }}>自动订阅：银河快报推送</Text>
      </Box>
    </Box>
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>05 / 12</Text>
  </Box>
</Slide>
