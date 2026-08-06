<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>三步装上战略终端</Text>
  </Box>
  <Box style={{ height:504, flexDirection:'row', gap:32 }}>
    <Box style={{ width:'34%', background:'linear-gradient(160deg,#16335C 0%,#0B1424 100%)', borderRadius:16, padding:32, justifyContent:'center' }}>
      <FAIcon name='rocket' style={{ fill:'#F5A623', width:56, height:56, marginBottom:18 }} />
      <Text style={{ fontSize:24, fontWeight:'bold', color:'#EAF1FB', lineHeight:1.4 }}>几分钟{'\n'}就能上线</Text>
      <Text style={{ fontSize:15, color:'#8FA3BF', lineHeight:1.6, marginTop:12 }}>推荐插件市场一键装，手动也只需几条命令。</Text>
    </Box>
    <Box style={{ flex:1, flexDirection:'column', justifyContent:'space-between', padding:'4px 0' }}>
      {[
        { n:'1', t:'安装插件', d:'插件市场搜「绝地潜兵2数据查询助手」一键装，或 git clone 到插件目录', cmd:'git clone .../astrbot_plugin_Helldivers' },
        { n:'2', t:'安装依赖', d:'安装 Python 依赖，并准备 Chromium 截图环境', cmd:'pip install -r requirements.txt' },
        { n:'3', t:'启用配置', d:'WebUI 启用插件并重载，填写 api_contact 邮箱即可出图', cmd:'python -m playwright install chromium' },
      ].map((it, i) => (
        <Box key={i} style={{ flexDirection:'row', alignItems:'center', gap:18, background:'#10213B', borderRadius:14, padding:'16px 22px' }}>
          <Box style={{ width:50, height:50, borderRadius:50, background:'#3D9BE9', justifyContent:'center', alignItems:'center' }}>
            <Text style={{ fontSize:24, fontWeight:'bold', color:'#0B1424' }}>{it.n}</Text>
          </Box>
          <Box style={{ flex:1 }}>
            <Text style={{ fontSize:21, fontWeight:'bold', color:'#EAF1FB' }}>{it.t}</Text>
            <Text style={{ fontSize:15, color:'#9FB3CC', lineHeight:1.4, marginTop:2 }}>{it.d}</Text>
            <Text style={{ fontSize:15, fontFamily:'Consolas', color:'#F5A623', marginTop:6 }}>{it.cmd}</Text>
          </Box>
        </Box>
      ))}
    </Box>
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>11 / 12</Text>
  </Box>
</Slide>
