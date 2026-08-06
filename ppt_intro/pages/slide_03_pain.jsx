<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>群里的战报，还靠手动转？</Text>
  </Box>
  <Box style={{ height:504, flexDirection:'row', gap:28 }}>
    <Box style={{ width:'60%', flexDirection:'column', justifyContent:'space-between' }}>
      {[
        { ic:'sync', c:'#F5A623', t:'手动刷网页', d:'战报靠人肉刷 Companion、Steam，慢且容易漏掉关键节点' },
        { ic:'language', c:'#3D9BE9', t:'英文看不懂', d:'原站全英文术语，新兵一脸懵，情报传到位却读不出重点' },
        { ic:'bell-slash', c:'#D64545', t:'战报错过', d:'B站银河快报发了才发现，群友早已错过这波进攻窗口' },
      ].map((it, i) => (
        <Box key={i} style={{ flexDirection:'row', alignItems:'flex-start', gap:18, background:'#10213B', borderRadius:14, padding:'20px 24px' }}>
          <Box style={{ width:54, height:54, borderRadius:14, background:'rgba(255,255,255,0.05)', justifyContent:'center', alignItems:'center', marginTop:2 }}>
            <FAIcon name={it.ic} style={{ fill:it.c, width:28, height:28 }} />
          </Box>
          <Box style={{ flex:1 }}>
            <Text style={{ fontSize:23, fontWeight:'bold', color:'#EAF1FB' }}>{it.t}</Text>
            <Text style={{ fontSize:18, color:'#9FB3CC', lineHeight:1.5, marginTop:4 }}>{it.d}</Text>
          </Box>
        </Box>
      ))}
    </Box>
    <Box style={{ width:'40%', background:'linear-gradient(160deg,#16335C 0%,#0B1424 100%)', border:'2px solid #F5A623', borderRadius:16, padding:32, justifyContent:'center' }}>
      <FAIcon name='check-circle' style={{ fill:'#F5A623', width:48, height:48, marginBottom:18 }} />
      <Text style={{ fontSize:30, fontWeight:'bold', color:'#F5A623', lineHeight:1.3 }}>一个插件{'\n'}全包了</Text>
      <Box style={{ width:80, height:3, background:'#3D9BE9', margin:'18px 0' }} />
      <Text style={{ fontSize:20, color:'#EAF1FB', lineHeight:1.9 }}>
        · 中文情报卡一键发群{'\n'}· 原网页自动翻译截图{'\n'}· 银河快报群内自动订阅
      </Text>
    </Box>
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>03 / 12</Text>
  </Box>
</Slide>
