var data = [{
  'text': 'gaming',
  'data': [{
    'text': 'simracing',
    'data': [{
      'text': 'level-3-menu',
      'data': []
  }]
}, {
  'text': 'crashday',
  'data': []
}, {
  'text': 'personal car game',
  'data': []
}]
}, {
  'text': 'k-pop',
  'data': [{
    'text': 'personal stuff',
    'data': []
}, {
    'text': 'playlists, recommended listening methods',
    'data': []
}, {
  'text': 'for sale',
  'data': []
}, {
  'text': 'shops i trust',
  'data': []
}]
}, {
  'text': 'misc',
  'data': [{
    'text': 'discord bot(s)',
    'data': []
}, {
    'text': 'car spotter app? (based on autoweek carbase, so eu-oriented)',
    'data': []
}]
}, {
  'text': 'about',
  'data': [{
    'text': 'this is me',
    'data': []
}, {
    'text': 'why this site',
    'data': []
}]
}];


function json_tree(data) {
var json = '<ul id="ul' + '">';

for(var i = 0; i < data.length; ++i) {
  json = json + "<li>" + "<a>" + data[i].text + "</a>";
  if(data[i].data.length) {
      json = json + json_tree(data[i].data);
  }
  json = json + "</li>";
}
return json + "</ul>";
}

document.getElementById("result").innerHTML = json_tree(data);
