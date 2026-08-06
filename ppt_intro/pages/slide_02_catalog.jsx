<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>目录<Text style={{ fontSize:20, color:'#8FA3BF', fontWeight:'normal' }}>　／　CONTENTS</Text></Text>
  </Box>
  <Box style={{ height:504, flexDirection:'row', gap:32 }}>
    <Box style={{ width:'34%', background:'linear-gradient(160deg,#16335C 0%,#0B1424 100%)', borderRadius:16, padding:32, justifyContent:'center' }}>
      <FAIcon name='compass' style={{ fill:'#F5A623', width:56, height:56, marginBottom:18 }} />
      <Text style={{ fontSize:24, color:'#EAF1FB', fontWeight:'bold', lineHeight:1.5 }}>四章看懂{'\n'}这个插件</Text>
      <Text style={{ fontSize:15, color:'#8FA3BF', lineHeight:1.6, marginTop:12 }}>从痛点价值到安装部署，一页不漏。</Text>
    </Box>
    <Box style={{ flex:1, flexDirection:'column', justifyContent:'space-between', padding:'6px 0' }}>
      {[
        { n:'01', ic:'exclamation-triangle', t:'痛点与价值', d:'为什么群里需要战略终端' },
        { n:'02', ic:'crosshairs', t:'核心功能', d:'指令 / 中文情报卡 / 地图 / DSS / 银河快报' },
        { n:'03', ic:'cogs', t:'技术底座', d:'架构设计与可靠性保障' },
        { n:'04', ic:'rocket', t:'安装与生态', d:'三步部署到你的机器人' },
      ].map((it, i) => (
        <Box key={i} style={{ flexDirection:'row', alignItems:'center', gap:20, background:'#10213B', borderRadius:12, padding:'18px 24px' }}>
          <Text style={{ fontSize:34, fontWeight:'bold', color:'#3D9BE9', width:62 }}>{it.n}</Text>
          <Box style={{ width:52, height:52, borderRadius:12, background:'rgba(61,155,233,0.12)', justifyContent:'center', alignItems:'center' }}>
            <FAIcon name={it.ic} style={{ fill:'#3D9BE9', width:26, height:26 }} />
          </Box>
          <Box style={{ flex:1 }}>
            <Text style={{ fontSize:22, fontWeight:'bold', color:'#EAF1FB' }}>{it.t}</Text>
            <Text style={{ fontSize:16, color:'#8FA3BF' }}>{it.d}</Text>
          </Box>
        </Box>
      ))}
    </Box>
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>02 / 12</Text>
  </Box>
</Slide>
