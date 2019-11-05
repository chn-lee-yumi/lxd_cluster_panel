from flask import Flask, request, redirect
import json
import time
from datetime import timedelta
import os
import flask_login

# 初始化Flask
app = Flask(__name__)
app.send_file_max_age_default = timedelta(seconds=30)
app.secret_key = "s1f3ha9q3sdahfkgu3p094oyi4r89pt0ua"
login_manager = flask_login.LoginManager()
login_manager.init_app(app)
data_time = 0

MODE = 'cluster'  # cluster或alone。cluster使用lxd原生cluster进行集群管理，alone则是由本系统进行集群管理。
SSH_PORT = '22'  # 服务器SSH端口
server_list = ['10.202.42.156', '10.202.42.157']  # 仅alone模式用

# TODO：实例规格API

######################以下是登录部分代码######################

users = {'admin': {'password': '12345'}}  # 前端页面的用户名密码


class User(flask_login.UserMixin):
    pass


@login_manager.user_loader
def user_loader(email):
    if email not in users:
        return
    user = User()
    user.id = email
    return user


@login_manager.request_loader
def request_loader(req):
    username = req.form.get('username')
    if username not in users:
        return
    user = User()
    user.id = username
    user.is_authenticated = req.form['password'] == users[username]['password']
    return user


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return app.send_static_file("login.html")
    username = request.form['username']
    try:
        if request.form['password'] == users[username]['password']:
            user = User()
            user.id = username
            flask_login.login_user(user)
            return redirect('/')
    except:
        pass
    return redirect('/login')


@app.route('/logout')
@flask_login.login_required
def logout():
    flask_login.logout_user()
    return app.send_static_file("login.html")


@login_manager.unauthorized_handler
def unauthorized_handler():
    return redirect('/login')


######################以上是登录部分代码######################


def collect_data():
    global cluster_data
    global instance_data
    global data_time
    cluster_data = get_cluster_data()
    instance_data = get_instance_data()
    data_time = time.time()


def get_node_info(ip: str, node: str = None) -> dict:
    """
    返回节点信息，包括配置和负载。
    :param ip: 节点ip地址（hostname也行，ssh需要能够解析）
    :param node: 节点名称（自定义）
    :return: 节点信息字典
    """
    if not node:
        node = ip
    sys_info = os.popen(
        'ssh -p' + SSH_PORT + ' ' + ip + " \"top -b -n 1 | head -n5 && lscpu | grep 'CPU(s):' | awk '{print $2}'\"").read().strip().split(
        '\n')
    cpu = 100 - float(sys_info[2].split()[7])
    core = sys_info[5].split()[1]
    cpu = "%.1f%% / %s核" % (cpu, core)
    load_tmp = sys_info[0].split()[-3:]
    load = load_tmp[0][:-1] + ' / ' + load_tmp[1][:-1] + ' / ' + load_tmp[2]
    load_5min = load_tmp[1][:-1]
    mem_total, mem_used = sys_info[3].split()[3:8:4]
    mem = "%dM / %dM / %.1f%%" % (round(int(mem_used) / 1024), round(int(mem_total) / 1024), round(int(mem_used) / int(mem_total) * 100, 1))
    swap_total, swap_used = sys_info[4].split()[2:7:4]
    if swap_total != '0':
        swap = "%dM / %dM / %.1f%%" % (
            round(int(swap_used) / 1024), round(int(swap_total) / 1024), round(int(swap_used) / int(swap_total) * 100, 1))
    else:
        swap = "0M / 0M / 0%"

    return {
        'node': node,
        'cpu': cpu,
        'load': load,
        'mem': mem,
        'swap': swap,
        'mem_used': int(mem_used),
        'mem_total': int(mem_total),
        'swap_used': int(swap_used),
        'swap_total': int(swap_total),
        'load_5min': float(load_5min),
        'core': int(core)
    }


def get_node_instances(ip: str = None) -> dict:
    """
    获取节点上运行的实例（仅针对alone模式）
    :param ip: 节点ip地址（hostname也行），如果为None，则为本机
    :return:
    """
    if not ip:
        lxc_list_raw = os.popen('sudo lxc list').read().split('\n')
    else:
        lxc_list_raw = os.popen('ssh -p' + SSH_PORT + ' ' + ip + ' sudo lxc list').read().split('\n')
    for line_num in range(3, len(lxc_list_raw) - 1, 2):
        line = list(map(lambda x: x.strip(' '), lxc_list_raw[line_num].split('|')))
        name = line[1]
        state = line[2]
        ipv4 = line[3]
        location = line[7]
        data.append({
            'name': name,
            'state': state,
            'ipv4': ipv4,
            'location': location,
        })

    pass


def get_cluster_data() -> list:
    """
    获取集群宿主信息
    :return:
    """
    data = []
    if MODE == 'cluster':  # 根据cluster模式或者alone模式分别处理
        lxc_cluster_list_raw = os.popen('sudo lxc cluster list').read().split('\n')
        for line_num in range(3, len(lxc_cluster_list_raw) - 1, 2):
            line = list(map(lambda x: x.strip(' '), lxc_cluster_list_raw[line_num].split('|')))
            node = line[1]
            ip = line[2].split('//')[1].split(':')[0]
            data.append(get_node_info(ip, node=node))
    elif MODE == 'alone':
        for ip in server_list:
            data.append(get_node_info(ip))

    return data


def get_instance_data() -> list:
    """
    获取集群实例信息
    :return:
    """
    data = []
    if MODE == 'cluster':  # 根据cluster模式或者alone模式分别处理
        data = get_node_instances()
    elif MODE == 'alone':
        for ip in server_list:
            data.extend(get_node_instances(ip))

    return data


def scheduler(core, mem):
    """调度器，创建容器时选择最佳节点 使用 --target node 指定节点"""
    global cluster_data
    global instance_data
    global data_time
    if time.time() - data_time > 10:
        collect_data()
    cluster_data = get_cluster_data()
    target_node = ''

    for node in cluster_data:
        # 检查CPU负载
        if node['load_5min'] >= node['core']:
            continue
        # 检查空余内存
        if mem[-2:] == 'GB':  # GB级只要50%空余内存
            if (node['mem_total'] - node['mem_used']) / 2 > int(mem[:-2]) * 1024 * 1024:
                target_node = node['node']
            else:
                continue
        else:  # MB级需要66.6%内存
            if (node['mem_total'] - node['mem_used']) / 1.5 > int(mem[:-2]) * 1024:
                target_node = node['node']
            else:
                continue

    return target_node


######################以下是API部分代码######################

@app.route("/")
@flask_login.login_required
def index():
    return app.send_static_file("index.html")


@app.route("/api/status")
@flask_login.login_required
def api_status():
    global cluster_data
    global instance_data
    global data_time
    if time.time() - data_time > 10:
        collect_data()
    return json.dumps({
        'clusterData': cluster_data,
        'instanceData': instance_data
    })


@app.route("/api/optInstance", methods=['POST'])
@flask_login.login_required
def api_opt_instance():
    data = json.loads(request.get_data(as_text=True))
    if "name" in data and "opt" in data:
        if data['name'].find(' ') != -1 or data['name'].find(';') != -1:
            return 'Error: not found'
        if data['opt'] in ['start', 'stop', 'restart', 'delete']:
            ret = os.popen('sudo lxc ' + data['opt'] + " " + data['name'] + " 2>&1").read()
            return ret


@app.route("/api/createInstance", methods=['POST'])
@flask_login.login_required
def api_create_instance():
    data = json.loads(request.get_data(as_text=True))
    if "name" in data and "system" in data and 'type' in data:
        name = data['name']
        core = data['type'].split('C')[0]
        mem = data['type'].split('C')[1] + "B"
        system = data['system']
        if system == "ubuntu18.04":
            system = "local:ubuntu18.04"
        # elif system == "debian10":
        #     system = "local:debian10"
        # elif system == "centos7":
        #     system = "local:centos7"
        else:
            return "系统不存在！"
        target_node = scheduler(core, mem)
        if not target_node:
            return '已经没有合适的宿主机，请选小一点的规格QwQ'
        ret = os.popen(
            ' '.join(['sudo', 'bash', '~/lxd_cluster_panel/lxc-run.sh', name, system, core, mem, target_node, "2>&1", "> /dev/null"])).read()
        return ret


if __name__ == '__main__':
    app.run('0.0.0.0', port=8080)
